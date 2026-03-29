import time
import logging
from collections import defaultdict
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """
    In-memory rate limiter.
    For single-instance Azure App Service B2 deployment this is sufficient.
    For multi-worker production, replace _requests with Redis.

    rules: dict mapping endpoint prefix -> (max_requests, window_seconds)
    Most specific prefix wins.
    """

    def __init__(self, app, rules: dict = None):
        super().__init__(app)
        self.rules = rules or {
            "/api/auth/request-otp": (5,   300),    # 5 per 5 min
            "/api/auth/verify-otp":  (10,  300),    # 10 per 5 min
            "/api/cases/submit":     (3,   3600),   # 3 per hour
            "/api/":                 (200, 60),     # 200 per min general
        }
        # key: (client_ip, rule_key) -> list of timestamps
        self._requests: dict = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip  = self._get_client_ip(request)
        path       = request.url.path
        rule_match = self._get_rule(path)

        if rule_match:
            rule_key, (max_req, window) = rule_match
            key = (client_ip, rule_key)
            now = time.time()

            # Evict expired timestamps
            self._requests[key] = [
                t for t in self._requests[key]
                if now - t < window
            ]

            if len(self._requests[key]) >= max_req:
                logger.warning(
                    f"Rate limit exceeded | ip={client_ip} | path={path} | "
                    f"count={len(self._requests[key])} | limit={max_req}/{window}s"
                )
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Too many requests. Maximum {max_req} requests "
                        f"per {window} seconds for this endpoint. "
                        f"Please wait and try again."
                    ),
                )

            self._requests[key].append(now)

        return await call_next(request)

    def _get_client_ip(self, request: Request) -> str:
        """
        Azure App Service passes real client IP in X-Forwarded-For.
        Fall back to direct connection IP.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def _get_rule(self, path: str):
        """
        Returns (rule_key, (max_req, window)) for the most specific
        matching prefix. Returns None if no rule matches.
        """
        best_key    = None
        best_rule   = None
        best_len    = 0

        for prefix, rule in self.rules.items():
            if path.startswith(prefix) and len(prefix) > best_len:
                best_key  = prefix
                best_rule = rule
                best_len  = len(prefix)

        if best_key:
            return best_key, best_rule
        return None
