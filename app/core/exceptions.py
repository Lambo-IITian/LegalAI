from fastapi import Request
from fastapi.responses import JSONResponse


class LegalAIException(Exception):
    def __init__(self, status_code: int, detail: str, error_code: str = "ERROR"):
        self.status_code = status_code
        self.detail      = detail
        self.error_code  = error_code


class CaseNotFound(LegalAIException):
    def __init__(self, case_id: str):
        super().__init__(404, f"Case {case_id} not found", "CASE_NOT_FOUND")


class UnauthorizedAccess(LegalAIException):
    def __init__(self):
        super().__init__(403, "You do not have access to this case", "UNAUTHORIZED")


class ContentSafetyViolation(LegalAIException):
    def __init__(self):
        super().__init__(400, "Submission contains inappropriate content",
                         "CONTENT_VIOLATION")


class InvalidCaseState(LegalAIException):
    def __init__(self, current: str, expected: str):
        super().__init__(
            409,
            f"Case is in state '{current}', expected {expected}",
            "INVALID_STATE"
        )


async def legalai_exception_handler(request: Request, exc: LegalAIException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error":  exc.error_code,
            "detail": exc.detail,
        },
    )