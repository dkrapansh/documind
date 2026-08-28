from sqlalchemy.orm import Session

from app.models.document_content import DocumentContent


def upsert_content(db: Session, document_id: int, extracted_text: str) -> None:
    """Store (or replace) a document's extracted text. Does NOT commit: the
    caller commits this in the same transaction as the document row, so a
    document can never exist without the text its ingestion job will need."""
    existing = db.query(DocumentContent).filter(
        DocumentContent.document_id == document_id
    ).first()
    if existing is not None:
        existing.text = extracted_text
        return
    db.add(DocumentContent(document_id=document_id, text=extracted_text))


def get_text(db: Session, document_id: int) -> str | None:
    """The ingestion worker's input. Returns None if no extraction exists,
    which the worker treats as a permanent failure rather than retrying: no
    amount of retrying will make missing text appear."""
    content = db.query(DocumentContent).filter(
        DocumentContent.document_id == document_id
    ).first()
    return content.text if content is not None else None


def delete_by_document(db: Session, document_id: int) -> None:
    """Does NOT commit. Called by the document delete path, which removes
    chunks, content, and the document row in one transaction."""
    db.query(DocumentContent).filter(
        DocumentContent.document_id == document_id
    ).delete(synchronize_session=False)


def delete_by_tenant(db: Session, tenant_id: int) -> None:
    """Does NOT commit. Used by the ephemeral tenant sweep.

    document_contents has no tenant_id of its own (it is strictly 1:1 with a
    document, which owns the tenant relationship), so this deletes via a
    subquery on documents rather than duplicating the column. The subquery is
    still tenant-scoped inside the SQL, which is what the tenancy rule
    actually requires.
    """
    from app.models.document import Document

    document_ids = db.query(Document.id).filter(Document.tenant_id == tenant_id).subquery()
    db.query(DocumentContent).filter(
        DocumentContent.document_id.in_(document_ids.select())
    ).delete(synchronize_session=False)
