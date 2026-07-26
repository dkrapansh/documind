import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.repositories.api_keys import delete_by_tenant as delete_keys_by_tenant
from app.repositories.chunks import delete_by_tenant as delete_chunks_by_tenant
from app.repositories.documents import delete_by_tenant as delete_documents_by_tenant
from app.repositories.query_logs import delete_by_tenant as delete_query_logs_by_tenant
from app.repositories.tenants import delete as delete_tenant, get_expired_ephemeral

logger = logging.getLogger(__name__)

def sweep_expired_ephemeral_tenants(db: Session) -> int:
    """Deletes every ephemeral tenant (and its keys/documents/chunks/
    query logs) older than settings.ephemeral_tenant_ttl_minutes.

    Called lazily from POST /auth/demo-session rather than on a cron -
    Render's free tier has no scheduler, and piggybacking on the one
    endpoint that creates ephemeral tenants means cleanup keeps pace
    with creation without needing separate infrastructure.
    """
    expired = get_expired_ephemeral(db, settings.ephemeral_tenant_ttl_minutes)
    for tenant in expired:
        delete_chunks_by_tenant(db, tenant.id)
        delete_documents_by_tenant(db, tenant.id)
        delete_query_logs_by_tenant(db, tenant.id)
        delete_keys_by_tenant(db, tenant.id)
        delete_tenant(db, tenant.id)
    db.commit()
    if expired:
        logger.info("swept %d expired ephemeral tenant(s)", len(expired))
    return len(expired)
