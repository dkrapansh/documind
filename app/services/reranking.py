from sqlalchemy.orm import Session

from app.clients.reranker import rerank_chunks
from app.config import settings
from app.schemas.query import RetrievedChunk
from app.services.hybrid_retrieval import hybrid_retrieve

CANDIDATE_K = 10
FINAL_TOP_K = 4

def retrieve_ranked(
    db: Session,
    tenant_id: int,
    question: str,
    confidence_threshold: float | None = None,
) -> list[RetrievedChunk]:
    """The full hybrid retrieval funnel POST /query actually calls:
    RRF-fused candidates from dense + BM25 (hybrid_retrieval.py), cross-
    encoder reranked (clients/reranker.py), cut to the final top_k.

    Returns an empty list, a refusal signal, when there are no
    candidates at all or the best-reranked candidate scores below the
    confidence threshold. Refusing here, before the LLM is ever
    called, is deterministic (unlike relying on the system prompt
    alone) and skips a paid LLM call when the context is already
    known to be weak.

    confidence_threshold defaults to settings.confidence_threshold but
    can be overridden per-call: the eval harness uses this to re-run
    the golden set against a candidate threshold without mutating
    settings.
    """
    if confidence_threshold is None:
        confidence_threshold = settings.confidence_threshold

    candidates = hybrid_retrieve(db, tenant_id, question, top_k=CANDIDATE_K)
    if not candidates:
        return []

    ranked = rerank_chunks(question, candidates)
    top_ranked = ranked[:FINAL_TOP_K]

    best_chunk, best_score = top_ranked[0]
    if best_score < confidence_threshold:
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
