import logging
import time
import uuid
from functools import wraps
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings

logger = logging.getLogger(__name__)


class MonitoringMiddleware(BaseHTTPMiddleware):
    """
    Logs every request with timing, status code, and request ID.
    Sends to Application Insights if configured.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start      = time.time()

        # Add request ID to headers for tracing
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            duration = (time.time() - start) * 1000

            logger.info(
                f"REQUEST | {request.method} {request.url.path} | "
                f"status={response.status_code} | "
                f"duration={duration:.0f}ms | "
                f"id={request_id}"
            )

            # Track slow requests
            if duration > 5000:
                logger.warning(
                    f"SLOW REQUEST | {request.url.path} | "
                    f"duration={duration:.0f}ms | id={request_id}"
                )

            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error(
                f"REQUEST ERROR | {request.method} {request.url.path} | "
                f"error={type(e).__name__} | duration={duration:.0f}ms | "
                f"id={request_id}"
            )
            raise


def setup_app_insights():
    """
    Connect Python logging to Azure Application Insights.
    Call this once at startup.
    """
    key = settings.APPINSIGHTS_INSTRUMENTATION_KEY
    if not key:
        logger.info("App Insights not configured — skipping")
        return

    try:
        from opencensus.ext.azure.log_exporter import AzureLogHandler
        from opencensus.ext.azure.trace_exporter import AzureExporter
        from opencensus.trace.samplers import ProbabilitySampler

        # Log handler — sends WARNING+ logs to App Insights
        azure_handler = AzureLogHandler(
            connection_string=f"InstrumentationKey={key}"
        )
        azure_handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(azure_handler)

        logger.info("Azure Application Insights logging enabled")

    except ImportError:
        logger.warning(
            "opencensus-ext-azure not installed. "
            "Run: pip install opencensus-ext-azure"
        )
    except Exception as e:
        logger.warning(f"App Insights setup failed (non-critical): {e}")


def track_agent_call(agent_name: str, track: str, success: bool, duration_ms: float):
    """Log individual agent calls for performance monitoring."""
    logger.info(
        f"AGENT | name={agent_name} | track={track} | "
        f"success={success} | duration={duration_ms:.0f}ms"
    )
    if not success:
        logger.warning(f"AGENT FAILED | name={agent_name} | track={track}")


def track_case_event(case_id: str, event: str, details: dict = None):
    """Log important case lifecycle events."""
    logger.info(
        f"CASE_EVENT | case_id={case_id[:8]} | event={event} | "
        f"details={details or {}}"
    )


def track_email_sent(to_email: str, email_type: str, success: bool):
    """Log email delivery attempts."""
    level = logging.INFO if success else logging.WARNING
    logger.log(
        level,
        f"EMAIL | type={email_type} | to={to_email[:3]}***@*** | success={success}"
    )