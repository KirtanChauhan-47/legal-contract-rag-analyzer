class AppException(Exception):
    """Base class for all application-raised errors.

    Carries an HTTP status code and a stable machine-readable error code so
    error_handlers.py can turn any of these into a consistent JSON shape
    instead of leaking a raw traceback to the client.
    """

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, error_code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if error_code is not None:
            self.error_code = error_code
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppException):
    status_code = 404
    error_code = "not_found"


class ValidationError(AppException):
    status_code = 422
    error_code = "validation_error"


class ConflictError(AppException):
    """Raised when an action is attempted out of order against the document
    processing status machine (e.g. asking a question before a document is
    embedded)."""

    status_code = 409
    error_code = "conflict"


class RateLimitedError(AppException):
    """Raised when the configured LLM provider's own rate/quota limit is
    hit. Distinct from ConflictError (which is about our status-machine
    ordering) -- this is an upstream provider constraint, surfaced as a
    clean 429 rather than a generic 500, without leaking provider-internal
    details (org IDs, raw error bodies) to the client."""

    status_code = 429
    error_code = "rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: int | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
