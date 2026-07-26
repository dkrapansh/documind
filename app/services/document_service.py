from sqlalchemy.orm import Session

from app.repositories.chunks import delete_by_document
from app.repositories.documents import delete_for_tenant
from app.services.query_cache import bump_scope


def delete_document(db: Session, document_id: int, tenant_id: int) -> bool:
    """Deletes a document and its chunks as one transaction and bumps
    the tenant's cache-scope version on success. Returns False, with
    nothing committed, if the document doesn't exist or belongs to
    another tenant, so the router can 404 correctly.

    Chunks are deleted first since chunks.document_id has no ON DELETE
    CASCADE at the DB level (see repositories/chunks.py).
    """
    delete_by_document(db, document_id, tenant_id)
    deleted = delete_for_tenant(db, document_id, tenant_id)
    if not deleted:
        db.rollback()
        return False
    db.commit()
    bump_scope(tenant_id)
    return True
