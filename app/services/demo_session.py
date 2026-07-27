import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import DemoCapacityExceededException
from app.models.tenant import Tenant
from app.repositories.api_keys import create_api_key
from app.repositories.tenants import count_ephemeral, create_tenant
from app.services.demo_seed import clone_seed_corpus
from app.services.tenant_cleanup import sweep_expired_ephemeral_tenants


def mint_demo_session(db: Session) -> tuple[Tenant, str]:
    """The full POST /auth/demo-session flow once the rate limit has
    already cleared: sweep expired tenants, enforce the global live-tenant
    cap, mint a fresh one, clone the seed corpus into it, and issue its
    key. Kept out of the router, which only owns the rate-limit check
    itself.
    """
    sweep_expired_ephemeral_tenants(db)

    if count_ephemeral(db) >= settings.max_live_ephemeral_tenants:
        raise DemoCapacityExceededException()

    tenant_name = f"demo-session-{uuid.uuid4().hex[:12]}"
    tenant = create_tenant(db, name=tenant_name, is_ephemeral=True)
    clone_seed_corpus(db, tenant.id)
    _, raw_key = create_api_key(db, tenant_id=tenant.id)
    return tenant, raw_key
