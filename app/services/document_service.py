from sqlalchemy.orm import Session

from app.repositories.chunks import delete_by_document
from app.repositories.document_contents import delete_by_document as delete_content_by_document
from app.repositories.documents import delete_for_tenant
from app.services.query_cache import bump_scope


def delete_document(db: Session, document_id: int, tenant_id: int) -> bool:
    """Deletes a document and its chunks as one transaction and bumps
    the tenant's cache-scope version on success. Returns False, with
    nothing committed, if the document doesn't exist or belongs to
    another tenant, so the router can 404 correctly.

    Chunks and extracted content are deleted first since neither has an
    ON DELETE CASCADE at the DB level (see repositories/chunks.py). Content
    is keyed only by document_id, so it is deleted after the tenant-scoped
    chunk delete and before the tenant-scoped document delete, which is what
    establishes that this document belongs to this tenant at all.
    """
    delete_by_document(db, document_id, tenant_id)
    delete_content_by_document(db, document_id)
    deleted = delete_for_tenant(db, document_id, tenant_id)
    if not deleted:
        db.rollback()
        return False
    db.commit()
    bump_scope(tenant_id)
    return True
