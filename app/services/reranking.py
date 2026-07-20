from sqlalchemy.orm import Session

from app.clients.reranker import rerank_chunks
from app.config import settings
from app.schemas.query import RetrievedChunk
from app.services.hybrid_retrieval import hybrid_retrieve

CANDIDATE_K = 10
FINAL_TOP_K = 4

def retrieve_ranked(db: Session, tenant_id: int, question: str) -> list[RetrievedChunk]:
    """The full hybrid retrieval funnel POST /query actually calls:
    RRF-fused candidates from dense + BM25 (hybrid_retrieval.py), cross-
    encoder reranked (clients/reranker.py), cut to the final top_k.

    Returns an empty list - a refusal signal, not an error - when there
    are no candidates at all, or when even the best-reranked candidate
    scores below settings.confidence_threshold. Refusing here, before
    ever calling the LLM, is a deliberate second line of defense beyond
    the system prompt's "say so if insufficient" instruction: it's
    deterministic (doesn't depend on the model choosing to comply) and
    it skips a paid LLM call entirely when we already know the context
    is weak.
    """
    candidates = hybrid_retrieve(db, tenant_id, question, top_k=CANDIDATE_K)
    if not candidates:
        return []

    ranked = rerank_chunks(question, candidates)
    top_ranked = ranked[:FINAL_TOP_K]

    best_chunk, best_score = top_ranked[0]
    if best_score < settings.confidence_threshold:
        return []

    return [
        RetrievedChunk(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            confidence=float(score),
        )
        for chunk, score in top_ranked
    ]
