"""Application errors. The API maps each to an HTTP status and stable code."""


class ApplicationError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        super().__init__(message or self.code)
        if code:
            self.code = code


class Unauthenticated(ApplicationError):
    status = 401
    code = "unauthenticated"


class AccessDenied(ApplicationError):
    """403, or a concealed 404 when policy must not disclose existence."""

    status = 403
    code = "forbidden"

    def __init__(self, message: str = "", *, code: str | None = None, conceal: bool = False):
        super().__init__(message, code=code)
        self.conceal = conceal


class NotFound(ApplicationError):
    status = 404
    code = "not_found"


class Conflict(ApplicationError):
    status = 409
    code = "conflict"


class StaleVersion(Conflict):
    code = "stale_version"


class IdempotencyConflict(Conflict):
    code = "idempotency_key_reused"


class PreconditionRequired(ApplicationError):
    status = 428
    code = "precondition_required"


class Unprocessable(ApplicationError):
    status = 422
    code = "invalid_input"
