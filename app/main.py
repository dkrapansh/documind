from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routers import health, auth, documents, history, query, eval
from app.core.exceptions import AppException
from app.middleware.auth import AuthMiddleware
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

app = FastAPI(title="DocuMind", version="0.1.0")

# Execution order per request: CorrelationID -> Auth -> RateLimit -> route.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(CorrelationIdMiddleware)

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(history.router)
app.include_router(eval.router)