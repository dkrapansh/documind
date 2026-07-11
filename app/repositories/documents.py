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