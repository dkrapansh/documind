from app.clients.reranker import rerank_chunks
from app.schemas.query import FusedChunk

def test_rerank_chunks_ranks_relevant_chunk_above_irrelevant_chunk():
    relevant = FusedChunk(
        id=1,
        document_id=1,
        chunk_index=0,
        text="Our refund policy allows returns within 30 days of purchase.",
        rrf_score=0.0,
    )
    irrelevant = FusedChunk(
        id=2,
        document_id=1,
        chunk_index=1,
        text="The quarterly report shows steady revenue growth in Q3.",
        rrf_score=0.0,
    )

    results = rerank_chunks("What is the refund policy?", [irrelevant, relevant])

    assert results[0][0].id == 1
    assert results[0][1] > results[1][1]
