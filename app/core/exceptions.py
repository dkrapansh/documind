class AppException(Exception):
    """Base class for expected application errors. Anything mapping to
    a specific HTTP status should subclass this, not raise a bare
    Exception or HTTPException, so every error is either an
    AppException (expected) or a genuine bug (unhandled 500).

    `code` is a stable, machine-readable identifier for the error, separate
    from `detail`, which is prose for a human. Clients that need to branch on
    an error (retry a timeout, prompt a re-upload, show a quota message)
    should switch on `code`; matching on `detail` breaks the moment the
    wording is improved.
    """

    status_code: int = 500
    detail: str = "Internal server error"
    code: str = "internal_error"


class InvalidAPIKeyException(AppException):
    status_code = 401
    code = "invalid_api_key"
    detail = "Invalid or missing API key"


class RateLimitExceededException(AppException):
    status_code = 429
    code = "rate_limit_exceeded"
    detail = "Rate limit exceeded"

class UnsupportedFileTypeException(AppException):
    status_code = 400
    code = "unsupported_file_type"

    def __init__(self, extension: str):
        self.detail = f"Unsupported file type '{extension}'. Supported: .txt, .pdf, .docx"
        super().__init__(self.detail)
    
class DocumentNotFoundException(AppException):
    status_code = 404
    code = "document_not_found"
    detail = "Document not found"

class EvalRunNotFoundException(AppException):
    status_code = 404
    code = "eval_run_not_found"
    detail = "Eval run not found"

class GenerationFailedException(AppException):
    status_code = 503
    code = "generation_failed"
    detail = "Answer generation failed. Please retry."

class EphemeralTenantForbiddenException(AppException):
    status_code = 403
    code = "ephemeral_tenant_forbidden"
    detail = "Ephemeral demo tenants cannot start evaluation runs"

class DemoCapacityExceededException(AppException):
    status_code = 503
    code = "demo_capacity_exceeded"
    detail = "The public demo is at capacity right now. Please try again in a few minutes."

class InvalidGoogleTokenException(AppException):
    status_code = 401
    code = "invalid_google_token"
    detail = "Invalid or expired Google login"

class UnreadableDocumentException(AppException):
    """Extraction ran and produced nothing usable. Raised during the upload
    request itself, now that extraction happens there: the caller finds out
    immediately, with a reason, instead of polling a document that silently
    lands in "failed" minutes later."""

    status_code = 422
    code = "unreadable_document"

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(self.detail)


class MissingFilenameException(AppException):
    status_code = 400
    code = "missing_filename"
    detail = "Upload is missing a filename. Send the file as a named multipart form field."


class PayloadTooLargeException(AppException):
    status_code = 413
    code = "payload_too_large"

    def __init__(self, max_bytes: int):
        self.detail = f"Uploaded file exceeds the maximum allowed size of {max_bytes} bytes"
        super().__init__(self.detail)

class RerankerUnavailableException(AppException):
    """The reranker could not be loaded or failed while scoring.

    503 rather than 500: the model load involves a download from a CDN this
    service does not control, so this is a dependency being unavailable
    rather than a bug in the request. A caller can reasonably retry.
    """

    status_code = 503
    code = "reranker_unavailable"
    detail = (
        "The ranking model is temporarily unavailable. Please retry in a moment."
    )


class EvalRunAlreadyActiveException(AppException):
    """An evaluation run is already in progress for this tenant.

    Each run is minutes of real model calls against a shared free-tier quota,
    so two concurrent runs do not just cost twice as much, they exhaust the
    quota and make both runs fail partway with null scores.
    """

    status_code = 409
    code = "eval_run_already_active"
    detail = (
        "An evaluation run is already in progress. Wait for it to finish before "
        "starting another."
    )
