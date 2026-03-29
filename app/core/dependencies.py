import logging
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from app.core.security import decode_token
from app.services.cosmos_service import cosmos_service

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency — validates JWT and returns user document from Cosmos.

    Usage in any protected route:
        current_user: dict = Depends(get_current_user)

    Raises HTTP 401 if token is missing, invalid, or expired.
    Raises HTTP 401 if user not found in Cosmos.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(credentials.credentials)
        email: str = payload.get("sub")
        if not email:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = cosmos_service.get_user_by_email(email)
    if not user:
        raise credentials_exception

    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> dict | None:
    """
    Same as get_current_user but returns None instead of raising
    for routes that work both authenticated and unauthenticated.
    Useful for the respondent portal where no account is required.
    """
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        email   = payload.get("sub")
        if not email:
            return None
        return cosmos_service.get_user_by_email(email)
    except JWTError:
        return None