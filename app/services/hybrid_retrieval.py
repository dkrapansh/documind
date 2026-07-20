from sqlalchemy.orm import Session

from app.schemas.query import FusedChunk
from app.services.bm25_retrieval import bm25_retrieve
from app.services.retrieval import retrieve

CANDIDATE_K = 10
RRF_K = 60

def hybrid_retrieve(
    db: Session, tenant_id: int, question: str, top_k: int = CANDIDATE_K
) -> list[FusedChunk]:
    """Merge dense (retrieval.py) and BM25 (bm25_retrieval.py) rankings
    with Reciprocal Rank Fusion: each chunk's fused score is the sum of
    1 / (RRF_K + rank) across every ranked list it appears in.

    RRF works on rank position, not raw score, which is what makes it
    safe to combine two retrievers whose scores live on incomparable
    scales (cosine distance vs. BM25's term-overlap score) — a chunk
    ranked #2 by both retrievers outscores one ranked #1 by only one,
    which is the entire point of hybrid search: reward chunks that
    multiple, differently-biased signals agree on.

    Each leg is queried for CANDIDATE_K candidates (more than the final
    top_k) so fusion has enough of the ranking to work with — a chunk
    that's #7 in dense but #1 in BM25 should still be able to win.

    No reranking or confidence threshold yet (Day 19) and not wired
    into /query yet.
    """
    dense_results = retrieve(db, tenant_id, question, top_k=CANDIDATE_K)
    bm25_results = bm25_retrieve(db, tenant_id, question, top_k=CANDIDATE_K)

    scores: dict[int, float] = {}
    chunks_by_id: dict[int, FusedChunk] = {}

    for ranked_list in (dense_results, bm25_results):
        for rank, chunk in enumerate(ranked_list, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (RRF_K + rank)
            if chunk.id not in chunks_by_id:
                chunks_by_id[chunk.id] = FusedChunk(
                    id=chunk.id,
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    rrf_score=0.0,
                )

    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

    return [
        chunks_by_id[cid].model_copy(update={"rrf_score": scores[cid]})
        for cid in ranked_ids[:top_k]
    ]
