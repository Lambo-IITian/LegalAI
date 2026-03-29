import logging
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel
from app.config import settings
from app.core.security import (
    generate_otp,
    create_access_token,
    get_otp_expiry,
    is_otp_expired,
)
from app.services.cosmos_service import cosmos_service
from app.services.email_service import email_service
from app.core.dependencies import get_current_user
from app.core.disclaimer import (
    DPDP_CONSENT_TEXT,
    AI_DISCLAIMER_TEXT,
    SETTLEMENT_DISCLAIMER,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class OTPRequest(BaseModel):
    email:        str
    display_name: str | None = None


class OTPVerify(BaseModel):
    email:        str
    otp:          str
    display_name: str | None = None
    phone:        str | None = None
    city:         str | None = None
    state:        str | None = None
    consent:      bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         dict


@router.post("/request-otp")
async def request_otp(body: OTPRequest):
    """
    Step 1 of login. Generates OTP, stores in Cosmos, sends via SendGrid.

    DEV MODE FALLBACK: If email send fails in development, OTP is printed
    to the server console so testing can continue without email service.
    """
    email      = body.email.strip().lower()
    otp        = generate_otp()
    expires_at = get_otp_expiry()

    cosmos_service.save_otp(email, otp, expires_at)

    existing = cosmos_service.get_user_by_email(email)
    name = (
        body.display_name
        or (existing.get("display_name") if existing else None)
        or email
    )

    sent = email_service.send_otp(email, otp, name)

    if not sent:
        if settings.ENVIRONMENT == "development":
            logger.warning(
                "\n" + "=" * 52 +
                "\n  EMAIL SEND FAILED — DEV MODE FALLBACK" +
                f"\n  OTP for {email}: {otp}" +
                f"\n  (valid for {settings.OTP_EXPIRE_MINUTES} minutes)" +
                "\n" + "=" * 52
            )
            return {
                "message":      "OTP generated (email failed in dev mode). Check the server console.",
                "email":        email,
                "dev_mode":     True,
                "email_failed": True,
            }
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to send OTP email. Please try again in a moment.",
        )

    logger.info(f"OTP sent | email={email}")
    return {"message": "OTP sent to your email. Valid for 10 minutes.", "email": email}


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(body: OTPVerify):
    """Step 2 of login. Verifies OTP, upserts user, issues JWT."""
    from datetime import datetime, timezone

    email = body.email.strip().lower()

    otp_record = cosmos_service.get_otp(email)
    if not otp_record:
        raise HTTPException(status_code=400, detail="OTP not found or already used. Request a new OTP.")

    if is_otp_expired(otp_record["expires_at"]):
        cosmos_service.delete_otp(email)
        raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

    if otp_record["otp"] != body.otp.strip():
        raise HTTPException(status_code=400, detail="Incorrect OTP. Please check and try again.")

    cosmos_service.delete_otp(email)

    user_data: dict = {"email": email}
    if body.display_name:
        user_data["display_name"] = body.display_name
    if body.phone:
        user_data["phone"] = body.phone.strip()
    if body.city:
        user_data["city"] = body.city.strip()
    if body.state:
        user_data["state"] = body.state.strip()
    if body.consent:
        user_data["consent_given"]           = True
        user_data["consent_given_at"]        = datetime.now(timezone.utc).isoformat()
        user_data["disclaimer_acknowledged"] = True

    existing = cosmos_service.get_user_by_email(email)
    if not user_data.get("display_name"):
        user_data["display_name"] = existing.get("display_name") if existing else email

    user  = cosmos_service.upsert_user(user_data)
    token = create_access_token({"sub": email})

    logger.info(f"User authenticated | email={email}")
    return TokenResponse(access_token=token, user=user)


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "id":                      current_user.get("id"),
        "email":                   current_user.get("email"),
        "display_name":            current_user.get("display_name"),
        "phone":                   current_user.get("phone"),
        "city":                    current_user.get("city"),
        "state":                   current_user.get("state"),
        "consent_given":           current_user.get("consent_given", False),
        "disclaimer_acknowledged": current_user.get("disclaimer_acknowledged", False),
        "created_at":              current_user.get("created_at"),
    }


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    logger.info(f"User logged out | email={current_user['email']}")
    return {"message": "Logged out. Please delete your token from client storage."}


@router.get("/disclaimers")
async def get_disclaimers():
    return {
        "dpdp_consent":      DPDP_CONSENT_TEXT,
        "ai_disclaimer":     AI_DISCLAIMER_TEXT,
        "settlement_notice": SETTLEMENT_DISCLAIMER,
    }
