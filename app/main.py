import logging
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.core.exceptions import LegalAIException, legalai_exception_handler
from app.core.rate_limiter import RateLimiterMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.input_validation import InputValidationMiddleware
from app.routers import auth, cases, negotiation, documents, respondent
from app.core.monitoring import MonitoringMiddleware, setup_app_insights

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="LegalAI Resolver",
    version="2.0.0",
    docs_url="/docs" if settings.ENVIRONMENT == "development" else None,
    redoc_url=None,
)

# ── Middleware (order matters — outermost runs first) ─────────
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(MonitoringMiddleware)
app.add_middleware(InputValidationMiddleware)
app.add_middleware(
    RateLimiterMiddleware,
    rules={
        "/api/auth/request-otp": (5,  300),
        "/api/auth/verify-otp":  (10, 300),
        "/api/cases/submit":     (3,  3600),
        "/api/":                 (200, 60),
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(
        ["*"] if settings.ENVIRONMENT == "development"
        else [settings.BASE_URL]
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception handlers ────────────────────────────────────────
app.add_exception_handler(LegalAIException, legalai_exception_handler)

# ── Routers ──────────────────────────────────────────────────
app.include_router(auth.router,        prefix="/api/auth",        tags=["auth"])
app.include_router(cases.router,       prefix="/api/cases",       tags=["cases"])
app.include_router(negotiation.router, prefix="/api/negotiation", tags=["negotiation"])
app.include_router(documents.router,   prefix="/api/documents",   tags=["documents"])
app.include_router(respondent.router,  prefix="/api/respondent",  tags=["respondent"])

# ── Static / Frontend ─────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse("frontend/index.html")


@app.get("/respond/{case_id}", include_in_schema=False)
async def serve_respondent_portal(case_id: str):
    return FileResponse("frontend/respond.html")


# ── Health Check ─────────────────────────────────────────────
@app.get("/health")
async def health_check():
    from app.services.cosmos_service import cosmos_service
    from app.services.blob_service import blob_service
    from app.services.openai_service import openai_service
    from app.services.content_safety import content_safety_service
    from app.services.email_service import email_service

    results = {}

    try:
        cosmos_service.db.read()
        results["cosmos_db"] = "ok"
    except Exception as e:
        results["cosmos_db"] = f"error: {str(e)[:60]}"

    try:
        list(blob_service.client.list_containers())
        results["blob_storage"] = "ok"
    except Exception as e:
        results["blob_storage"] = f"error: {str(e)[:60]}"

    try:
        openai_service.call(
            system_prompt="Reply with the word OK",
            user_message="ping",
            use_large_model=False,
            json_mode=False,
            max_tokens=5,
        )
        results["azure_openai"] = "ok"
    except Exception as e:
        results["azure_openai"] = f"error: {str(e)[:60]}"

    try:
        content_safety_service.check_text("This is a test message for health check.")
        results["content_safety"] = "ok"
    except Exception as e:
        results["content_safety"] = f"error: {str(e)[:60]}"

    try:
        if email_service.is_configured():
            results["email_service"] = "ok"
        else:
            results["email_service"] = "error: sendgrid not configured"
    except Exception as e:
        results["email_service"] = f"error: {str(e)[:60]}"

    results["environment"] = settings.ENVIRONMENT
    results["base_url"]    = settings.BASE_URL

    all_ok = all(
        "ok" in str(v)
        for k, v in results.items()
        if k not in ["environment", "base_url"]
    )

    return {
        "status":   "healthy" if all_ok else "degraded",
        "services": results,
    }


# ── Startup ───────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info(f"LegalAI Resolver v2.0 starting | env={settings.ENVIRONMENT}")
    setup_app_insights()

    from app.core.expiry_worker import start_expiry_worker
    asyncio.create_task(start_expiry_worker())
    logger.info("All systems started")


# ── App Insights Logging ──────────────────────────────────────
if settings.APPINSIGHTS_INSTRUMENTATION_KEY:
    try:
        from opencensus.ext.azure.log_exporter import AzureLogHandler
        azure_handler = AzureLogHandler(
            connection_string=f"InstrumentationKey={settings.APPINSIGHTS_INSTRUMENTATION_KEY}"
        )
        azure_handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(azure_handler)
        logger.info("Azure Application Insights logging enabled")
    except Exception as e:
        logger.warning(f"App Insights setup failed (non-critical): {e}")
