class AppException(Exception):
    """Base class for all custom, expected application errors.

    Anything raised from services/repositories that should map to a
    specific HTTP status code should subclass this, not raise a bare
    Exception or HTTPException directly. Keeping one hierarchy means
    every error in the system is either an AppException (expected,
    mapped) or a genuine bug (unhandled 500).
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