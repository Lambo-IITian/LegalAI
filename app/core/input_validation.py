# app/core/input_validation.py

import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from fastapi.responses import JSONResponse


class InputValidationMiddleware(BaseHTTPMiddleware):
    """
    Blocks obviously malicious requests before they reach route handlers.
    """

    # Patterns to block in URL path
    BLOCKED_PATH_PATTERNS = [
        r"\.\./",           # path traversal
        r"<script",         # XSS in URL
        r"javascript:",     # JS injection
        r"union\s+select",  # SQL injection
        r"exec\s*\(",       # code execution
    ]

    def __init__(self, app):
        super().__init__(app)
        self._compiled = [
            re.compile(p, re.IGNORECASE)
            for p in self.BLOCKED_PATH_PATTERNS
        ]

    async def dispatch(self, request: Request, call_next):
        path = str(request.url)

        for pattern in self._compiled:
            if pattern.search(path):
                return JSONResponse(
                    status_code=400,
                    content={"error": "INVALID_REQUEST", "detail": "Invalid request."},
                )

        return await call_next(request)