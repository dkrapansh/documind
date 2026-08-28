import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import APP_VERSION
from app.api.routers import health, auth, documents, history, query, eval
from app.config import settings
from app.core.exceptions import AppException
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.middleware.auth import AuthMiddleware
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.services.health import log_startup_diagnostics
from app.services.ingestion_worker import recover_stale, start_worker, stop_worker
from app.services.tenant_cleanup import sweep_expired_ephemeral_tenants

# Before uvicorn imports anything else, so the first startup log line is
# already formatted and carries a correlation id field. Without this the
# root logger stays at WARNING and every logger.info below is discarded.
configure_logging(settings.app_env, settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: record what this instance is, then best-effort sweep of
    expired ephemeral tenants, on top of the one POST /auth/demo-session
    already runs on every mint. Render has no cron, but the instance
    restarts on every deploy and cold start, so this catches abandoned
    tenants between restarts without needing new demo traffic. An
    instance that stays warm with no new traffic will still accumulate
    expired tenants between boots.

    Every step here is best-effort on purpose: an unreachable database
    must not prevent the process from binding a port. A booted instance
    that reports "not ready" through /health/ready is diagnosable; one
    that exited during startup is not, which is exactly the failure this
    deployment hit in production.
    """
    log_startup_diagnostics()

    db = SessionLocal()
    try:
        sweep_expired_ephemeral_tenants(db)
    except Exception:
        logger.exception("startup sweep of expired ephemeral tenants failed")
    finally:
        db.close()

    # A restart is exactly when stranded ingestion jobs exist, since the
    # thing that stranded them is usually the restart itself (a deploy, an
    # OOM kill, a platform move). Recovering here means a document caught
    # mid-ingestion by a deploy resumes on the next boot instead of sitting
    # at "processing" forever.
    try:
        recover_stale()
    except Exception:
        logger.exception("startup recovery of stale ingestion jobs failed")

    if settings.ingestion_worker_enabled:
        try:
            start_worker()
        except Exception:
            logger.exception("failed to start the ingestion worker")

    yield

    # Ask the worker to finish its current job and exit. A job still running
    # when the timeout expires is not lost: its lease expires and the next
    # process to boot reclaims it.
    stop_worker()


app = FastAPI(title="DocuMind", version=APP_VERSION, lifespan=lifespan)

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