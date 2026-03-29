from fastapi import HTTPException, status


def require_consent(user: dict):
    """
    Call this at the start of any case-filing endpoint.
    Raises 403 if user has not given DPDP consent.
    """
    if not user.get("consent_given"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Data consent required before filing a case. "
                "Please complete the consent flow in your profile."
            ),
        )
    if not user.get("disclaimer_acknowledged"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "AI disclaimer acknowledgment required. "
                "Please acknowledge that LegalAI outputs are AI-assisted, not legal advice."
            ),
        )


def require_complete_profile(user: dict):
    """
    Call this before case filing — profile must be complete.
    """
    if not user.get("display_name") or not user.get("phone"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please complete your profile (name and phone) before filing a case.",
        )