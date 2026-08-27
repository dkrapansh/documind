import json
import logging
import sys

from app.middleware.correlation_id import correlation_id_var

# Fields already present on every LogRecord. Anything a caller passes via
# logger.info(..., extra={...}) that isn't in here is treated as a custom
# field and merged into the JSON output, which is what lets call sites add
# tenant_id/latency_ms without this module knowing about them in advance.
# correlation_id is in here because CorrelationIdFilter attaches it to
# every record: both formatters render it in a fixed position, so leaving
# it out of this set would also print it a second time as a custom field.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"asctime", "message", "taskName", "correlation_id"}

# Never emit these, whatever a caller passes. Redaction lives at the
# formatter rather than at each call site, so a future logging statement
# can't leak a credential by forgetting to strip it first.
_REDACTED_KEYS = frozenset(
    {
        "api_key",
        "x_api_key",
        "raw_key",
        "hashed_key",
        "authorization",
        "cookie",
        "set_cookie",
        "password",
        "secret",
        "token",
        "id_token",
        "credential",
        "gemini_api_key",
        "database_url",
    }
)

_REDACTED = "[REDACTED]"


class CorrelationIdFilter(logging.Filter):
    """Copies the current request's correlation id onto every LogRecord.

    CorrelationIdMiddleware stores it in a ContextVar, which propagates
    into whatever code the request calls without threading an argument
    through every function. Before this filter existed the ContextVar was
    set and never read by anything, so correlation ids reached the
    response header and query_logs but not a single log line.

    Records emitted outside a request (startup, background jobs) get "-"
    rather than an empty string, so a log line is never ambiguous about
    whether the id is missing or just absent.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get() or "-"
        return True


def _extra_fields(record: logging.LogRecord) -> dict:
    return {
        key: (_REDACTED if key.lower() in _REDACTED_KEYS else value)
        for key, value in record.__dict__.items()
        if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for production.

    Render ships stdout to its log viewer as plain text, so structured
    fields are only greppable if they're in the line itself. JSON keeps
    them machine-parseable if logs are ever forwarded somewhere that can
    index them, without needing a logging backend today.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", "-"),
            "message": record.getMessage(),
        }
        payload.update(_extra_fields(record))

        if record.exc_info:
            # Stack traces stay server-side only. The HTTP error handler
            # returns an error code and the correlation id, never this.
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class HumanFormatter(logging.Formatter):
    """Readable single-line output for local development, where a wall of
    JSON is harder to scan than it is useful."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s [%(correlation_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extra_fields(record)
        if extras:
            base += " " + " ".join(f"{key}={value}" for key, value in extras.items())
        return base


def configure_logging(app_env: str, log_level: str) -> None:
    """Install the root handler once, at startup.

    Without this the application configures no logging at all: uvicorn sets
    up its own loggers but leaves the root logger at WARNING, so every
    logger.info in this codebase (the ephemeral tenant sweep, the eval
    refusal summary) was silently discarded, and logger.exception calls
    landed with no correlation id attached.

    uvicorn's own loggers are pointed at the same handler so access lines
    and application lines share one format instead of interleaving two.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if app_env == "production" else HumanFormatter())
    handler.addFilter(CorrelationIdFilter())

    root = logging.getLogger()
    # Replace rather than append, so calling this twice (tests, reload)
    # doesn't duplicate every line.
    root.handlers = [handler]
    root.setLevel(log_level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
