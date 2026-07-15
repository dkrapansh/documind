from sqlalchemy.orm import Session

from app.clients.embeddings import embed_text
from app.repositories.chunks import search_by_embedding
from app.schemas.query import RetrievedChunk

DEFAULT_TOP_K = 4

def retrieve(
     db: Session, tenant_id: int, question: str, top_k: int = DEFAULT_TOP_K   
) -> list[RetrievedChunk]:
    """Dense-only retrieval (v1): embed the question, find the top_k
    closest chunks for this tenant by cosine distance.

    No BM25, no fusion, no reranking yet, those will arrive during Days 17-19.
    This is the narrowest working slice of the retrieval funnel,
    verified correct before more stages get layered on top.
    """
    query_embedding = embed_text(question)
    results = search_by_embedding(db, tenant_id, query_embedding, top_k)

    return [
        RetrievedChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            distance=distance,
        )
        for chunk, distance in results
    ]