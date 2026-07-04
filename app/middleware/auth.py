from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.exceptions import InvalidAPIKeyException
from app.core.security import hash_key
from app.db.session import SessionLocal
from app.repositories.api_keys import get_by_hashed_key

EXCLUDED_PATHS = {
    "/health",
    "/readyz",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/keys",    
}

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)
        
        raw_key = request.headers.get("X-API-Key")
        if raw_key is None:
            return self._reject()
        
        db = SessionLocal()
        try:
            api_key = get_by_hashed_key(db, hash_key(raw_key))
        finally:
            db.close()
        
        if api_key is None:
            return self._reject()
        
        request.state.tenant_id = api_key.tenant_id
        request.state.api_key_id = api_key.id

        return await call_next(request)
    
    @staticmethod
    def _reject() -> JSONResponse:
        exc = InvalidAPIKeyException()
        return JSONResponse(status_code=exc.status_code, content = {"detail": exc.detail})