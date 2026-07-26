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

def search_by_embedding(
    db: Session,
    tenant_id: int,
    query_embedding: list[float],
    top_k: int,
) -> list[tuple[Chunk, float]]:
    """Top_k chunks closest by cosine distance to the query embedding,
    scoped to one tenant. Returns (Chunk, distance) pairs, smaller
    distance means more similar. HNSW-indexed, so ORDER BY stays fast
    as the table grows.
    """
    distance = Chunk.embedding.cosine_distance(query_embedding)
    results = (
        db.query(Chunk, distance.label("distance"))
        .filter(Chunk.tenant_id == tenant_id)
        .order_by(distance)
        .limit(top_k)
        .all()
    )
    return [(row[0], row[1]) for row in results]

def delete_by_document(db: Session, document_id: int, tenant_id: int) -> None:
    """Not a cascading FK, so the document delete in documents.py calls
    this first to avoid leaving orphaned chunk rows behind."""
    db.query(Chunk).filter(
        Chunk.document_id == document_id, Chunk.tenant_id == tenant_id
    ).delete()

def list_by_tenant(db: Session, tenant_id: int) -> list[Chunk]:
    """All chunks for a tenant, unscored. BM25 has no SQL-level index,
    it needs the whole corpus in memory to score, so this just does
    the tenant-scoped fetch; scoring happens in the service layer.
    """
    return (
        db.query(Chunk)
        .filter(Chunk.tenant_id == tenant_id)
        .order_by(Chunk.id)
        .all()
    )