import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import health, auth, documents, history, query, eval
from app.config import settings
from app.core.exceptions import AppException
from app.db.session import SessionLocal
from app.middleware.auth import AuthMiddleware
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.services.tenant_cleanup import sweep_expired_ephemeral_tenants

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Best-effort sweep of expired ephemeral tenants on boot, on top of
    the one POST /auth/demo-session already runs on every mint. Render
    has no cron, but the instance restarts on every deploy and cold
    start, so this catches abandoned tenants between restarts without
    needing new demo traffic. An instance that stays warm with no new
    traffic will still accumulate expired tenants between boots.
    """
    db = SessionLocal()
    try:
        sweep_expired_ephemeral_tenants(db)
    except Exception:
        logger.exception("startup sweep of expired ephemeral tenants failed")
    finally:
        db.close()
    yield


app = FastAPI(title="DocuMind", version="0.1.0", lifespan=lifespan)

# Execution order per request: CorrelationID -> Auth -> RateLimit -> route.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(CorrelationIdMiddleware)
# Runs outermost so it can attach CORS headers to error responses too
# (including the 401s the auth middleware above returns) - otherwise a
# rejected browser request fails with an opaque CORS error instead of a
# readable 401.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Content-Type"],
)

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(query.router)
app.include_router(history.router)
app.include_router(eval.router)