import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.core.exceptions import RateLimitExceededException

_request_counts: dict[int, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key_id = getattr(request.state, "api_key_id", None)
        if api_key_id is None:
            # No key resolved(excluded path, or auth already rejected it - nothing to rate limit against)
            return await call_next(request)
        
        now = time.time()
        window_start, count = _request_counts[api_key_id]

        if now - window_start > settings.rate_limit_window_seconds:
            window_start, count = now, 0

        count += 1
        _request_counts[api_key_id] = (window_start, count)

        if count > settings.rate_limit_requests:
            exc = RateLimitExceededException()
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        
        return await call_next(request)