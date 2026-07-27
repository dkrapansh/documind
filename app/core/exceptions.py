class AppException(Exception):
    """Base class for expected application errors. Anything mapping to
    a specific HTTP status should subclass this, not raise a bare
    Exception or HTTPException, so every error is either an
    AppException (expected) or a genuine bug (unhandled 500).
    """

    status_code: int = 500
    detail: str = "Internal server error"


class InvalidAPIKeyException(AppException):
    status_code = 401
    detail = "Invalid or missing API key"


class RateLimitExceededException(AppException):
    status_code = 429
    detail = "Rate limit exceeded"

class UnsupportedFileTypeException(AppException):
    status_code = 400

    def __init__(self, extension: str):
        self.detail = f"Unsupported file type '{extension}'. Supported: .txt, .pdf, .docx"
        super().__init__(self.detail)
    
class DocumentNotFoundException(AppException):
    status_code = 404
    detail = "Document not found"

class EvalRunNotFoundException(AppException):
    status_code = 404
    detail = "Eval run not found"

class GenerationFailedException(AppException):
    status_code = 503
    detail = "Answer generation failed. Please retry."

class EphemeralTenantForbiddenException(AppException):
    status_code = 403
    detail = "Ephemeral demo tenants cannot start evaluation runs"

class DemoCapacityExceededException(AppException):
    status_code = 503
    detail = "The public demo is at capacity right now. Please try again in a few minutes."

class PayloadTooLargeException(AppException):
    status_code = 413

    def __init__(self, max_bytes: int):
        self.detail = f"Uploaded file exceeds the maximum allowed size of {max_bytes} bytes"
        super().__init__(self.detail)