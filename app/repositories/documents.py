from sqlalchemy.orm import Session

from app.models.document import Document

def get_by_content_hash(db: Session, tenant_id: int, content_hash: str) -> Document | None:
    return db.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.content_hash == content_hash,
    ).first()

def create_document(
        db: Session, tenant_id: int, filename: str, content_hash: str
) -> Document:
    document = Document(
        tenant_id = tenant_id,
        filename = filename,
        content_hash = content_hash,
        status = "pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document

def create_ready_document(
        db: Session, tenant_id: int, filename: str, content_hash: str, chunk_count: int
) -> Document:
    """Used only by the demo-seed cloner (services/demo_seed.py) - skips
    the pending/processing states because the chunks it's about to attach
    are copies of already-embedded ones, not freshly extracted text."""
    document = Document(
        tenant_id=tenant_id,
        filename=filename,
        content_hash=content_hash,
        status="ready",
        chunk_count=chunk_count,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document

def get_by_id(db: Session, document_id: int) -> Document | None:
    return db.query(Document).filter(Document.id == document_id).first()

def update_status(
        db: Session, document_id: int, status: str, chunk_count: int | None = None
) -> None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        return
    document.status = status
    if chunk_count is not None:
        document.chunk_count = chunk_count
    
def get_by_id_for_tenant(db: Session, document_id: int, tenant_id: int) -> Document | None:
    return db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id,
    ).first()

def delete_by_tenant(db: Session, tenant_id: int) -> None:
    db.query(Document).filter(Document.tenant_id == tenant_id).delete()

def delete_for_tenant(db: Session, document_id: int, tenant_id: int) -> bool:
    """Deletes only the document row. Returns False without deleting
    anything if it doesn't exist or belongs to another tenant, so
    callers can 404 correctly. Caller must delete the document's chunks
    first (chunks.document_id has no ON DELETE CASCADE at the DB level)
    and commit both in one transaction."""
    document = get_by_id_for_tenant(db, document_id, tenant_id)
    if document is None:
        return False
    db.delete(document)
    return True

def list_by_tenant(db: Session, tenant_id: int) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .order_by(Document.upload_time.desc())
        .all()
    )