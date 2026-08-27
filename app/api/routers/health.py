from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.health import liveness, readiness

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Liveness (legacy path)",
    description=(
        "Alias of `/health/live`, kept so existing platform health checks and "
        "bookmarks do not break. New callers should use `/health/live`."
    ),
)
def health_check():
    return liveness()


@router.get(
    "/health/live",
    summary="Liveness probe",
    description=(
        "Returns 200 whenever the process is running and able to serve HTTP. "
        "Touches no database and no external provider, so a dependency outage "
        "cannot make an otherwise healthy instance look dead and get restarted "
        "into the same failure. This is the endpoint a platform health check "
        "should target."
    ),
)
def health_live():
    return liveness()


@router.get(
    "/health/ready",
    summary="Readiness probe",
    description=(
        "Reports whether this instance can actually serve a query, along with "
        "its version, git SHA, environment, and per-dependency status. Returns "
        "503 when a dependency required to serve traffic is unhealthy, so a "
        "caller can distinguish 'still waking up' from 'awake but broken'. "
        "Never returns secrets: no connection string, API key, or header value."
    ),
    responses={503: {"description": "A dependency required to serve traffic is unhealthy."}},
)
def health_ready():
    ready, payload = readiness()
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload
