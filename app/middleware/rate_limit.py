import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.middleware.correlation_id import correlation_id_var

from app.config import settings
from app.core.exceptions import error_body, RateLimitExceededException

_request_counts: dict[int, tuple[float, int]] = defaultdict(lambda: (0.0, 0))
# Never evicts a key, only resets its window - a full clear once this
# gets implausibly large is a blunt but simple bound on otherwise
# unbounded growth over a long-running process's lifetime.
_MAX_TRACKED_KEYS = 50_000

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key_id = getattr(request.state, "api_key_id", None)
        if api_key_id is None:
            # No key resolved(excluded path, or auth already rejected it - nothing to rate limit against)
            return await call_next(request)

        if len(_request_counts) > _MAX_TRACKED_KEYS:
            _request_counts.clear()

        now = time.time()
        window_start, count = _request_counts[api_key_id]

        if now - window_start > settings.rate_limit_window_seconds:
            window_start, count = now, 0

        count += 1
        _request_counts[api_key_id] = (window_start, count)

        if count > settings.rate_limit_requests:
            exc = RateLimitExceededException()
            return JSONResponse(
                status_code=exc.status_code,
                content=error_body(exc, correlation_id_var.get()),
            )
        
        return await call_next(request)