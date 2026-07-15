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

def get_by_id(db: Session, document_id: int) -> Document | None:
    return db.query(Document).filter(Document.id == document_id).first()

def update_status(
        db: Session, document_id: int, status: str, chunk_count: int | None = None
) -> None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        return
    document_status = status
    if chunk_count is not None:
        document.chunk_count = chunk_count
    
def get_by_id_for_tenant(db: Session, document_id: int, tenant_id: int) -> Document | None:
    return db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id,
    ).first()

def get_by_id_for_tenant(db: Session, document_id: int, tenant_id: int) -> Document | None:
    return db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id,
    ).first()