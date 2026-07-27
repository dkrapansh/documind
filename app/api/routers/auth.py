import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.config import settings
from app.core.exceptions import RateLimitExceededException
from app.repositories.api_keys import create_api_key, revoke
from app.repositories.tenants import create_tenant
from app.schemas.auth import CreateKeyRequest, CreateKeyResponse
from app.services.demo_session import mint_demo_session

router = APIRouter(prefix="/auth", tags=["auth"])

# Same unbounded-growth guard as middleware/rate_limit.py's _MAX_TRACKED_KEYS.
_MAX_TRACKED_KEYS = 50_000

# In-memory, single-instance limiter, same tradeoff and pattern as the
# demo-session one below - /auth/keys is the other route that has to
# stay unauthenticated (there's no key yet to authenticate with).
_create_key_counts: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

@router.post("/keys", response_model=CreateKeyResponse)
def issue_key(payload: CreateKeyRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"

    if len(_create_key_counts) > _MAX_TRACKED_KEYS:
        _create_key_counts.clear()

    now = time.time()
    window_start, count = _create_key_counts[ip]
    if now - window_start > settings.auth_keys_rate_limit_window_seconds:
        window_start, count = now, 0
    count += 1
    _create_key_counts[ip] = (window_start, count)
    if count > settings.auth_keys_rate_limit:
        raise RateLimitExceededException()

    tenant = create_tenant(db, name=payload.tenant_name)
    _, raw_key = create_api_key(db, tenant_id = tenant.id)
    return CreateKeyResponse(api_key=raw_key, tenant_id=tenant.id)

@router.post("/keys/revoke", status_code=204, dependencies=[Depends(api_key_header)])
def revoke_key(request: Request, db: Session = Depends(get_db)):
    """Self-revoke: the caller can only revoke the key it authenticated
    with, not an arbitrary key ID - there's no cross-tenant key lookup
    exposed here on purpose."""
    revoke(db, request.state.api_key_id)
    return Response(status_code=204)

# In-memory, single-instance limiter for the one route that has to stay
# unauthenticated - same tradeoff as middleware/rate_limit.py, acceptable
# on Render's free tier (one instance).
_demo_session_counts: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))

def _client_ip(request: Request) -> str:
    """Rate-limit key for the one route that has to stay unauthenticated.

    A direct caller could set X-Forwarded-For to anything, so it's only
    trusted when paired with demo_proxy_shared_secret, known only to
    this backend and the proxy (frontend/api/_lib/session.js). No
    matching secret means fall back to the raw TCP peer address, which
    can't be forged. This also fixes the old demo-DoS: every proxy
    visitor used to collide on the proxy's own shared egress IP, so one
    abuser could exhaust the whole bucket for everyone.
    """
    secret = settings.demo_proxy_shared_secret
    if secret and request.headers.get("X-Demo-Proxy-Secret") == secret:
        visitor_ip = request.headers.get("X-Demo-Visitor-IP")
        if visitor_ip:
            return visitor_ip.strip()
    return request.client.host if request.client else "unknown"

@router.post("/demo-session", response_model=CreateKeyResponse)
def create_demo_session(request: Request, db: Session = Depends(get_db)):
    """Mints a throwaway, isolated tenant + key for one visitor of the
    public landing-page demo. Called by the frontend's server-side proxy,
    never directly by the browser, so the raw key never reaches client JS
    - see frontend/api/ for the proxy that calls this and holds the
    result in an httpOnly cookie.

    Each call gets its own tenant specifically so one visitor's uploads
    can never surface in another visitor's query results, which is what
    the single shared demo key used to allow.
    """
    ip = _client_ip(request)

    if len(_demo_session_counts) > _MAX_TRACKED_KEYS:
        _demo_session_counts.clear()

    now = time.time()
    window_start, count = _demo_session_counts[ip]
    if now - window_start > settings.demo_session_rate_limit_window_seconds:
        window_start, count = now, 0
    count += 1
    _demo_session_counts[ip] = (window_start, count)
    if count > settings.demo_session_rate_limit:
        raise RateLimitExceededException()

    tenant, raw_key = mint_demo_session(db)
    return CreateKeyResponse(api_key=raw_key, tenant_id=tenant.id)
