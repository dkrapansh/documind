from sqlalchemy.orm import Session

from app.models.chunk import Chunk

def create_chunks(
        db: Session,
        document_id: int, 
        tenant_id: int,
        chunks: list[dict],
) -> None:
    """Stage chunk rows for insert. Does NOT commit. The caller
    (ingestion.py) controls the transaction boundary, so all chunks
    and the document's status update land in one atomic commit."""

    for chunk in chunks:
        db.add(
            Chunk(
                document_id=document_id,
                tenant_id=tenant_id,
                chunk_index=chunk["index"],
                text=chunk["text"],
                embedding=chunk["embedding"],
                token_count=chunk["token_count"],
            )
        )