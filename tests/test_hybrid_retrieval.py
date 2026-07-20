from app.schemas.query import BM25Chunk, RetrievedChunk
from app.services.hybrid_retrieval import hybrid_retrieve

def test_hybrid_retrieve_rewards_chunk_present_in_both_rankings(monkeypatch):
    # X: dense rank 1, absent from BM25's results entirely.
    # Y: dense rank 2, BM25 rank 1 - present in both lists.
    dense_results = [
        RetrievedChunk(id=1, document_id=1, chunk_index=0, text="X", distance=0.1),
        RetrievedChunk(id=2, document_id=1, chunk_index=1, text="Y", distance=0.2),
    ]
    bm25_results = [
        BM25Chunk(id=2, document_id=1, chunk_index=1, text="Y", score=5.0),
    ]

    monkeypatch.setattr(
        "app.services.hybrid_retrieval.retrieve",
        lambda db, tenant_id, question, top_k: dense_results,
    )
    monkeypatch.setattr(
        "app.services.hybrid_retrieval.bm25_retrieve",
        lambda db, tenant_id, question, top_k: bm25_results,
    )

    results = hybrid_retrieve(db=None, tenant_id=1, question="irrelevant", top_k=2)

    assert [chunk.id for chunk in results] == [2, 1]
    assert results[0].rrf_score > results[1].rrf_score

def test_hybrid_retrieve_deduplicates_chunk_found_by_both_retrievers(monkeypatch):
    shared = RetrievedChunk(id=9, document_id=1, chunk_index=0, text="shared", distance=0.1)
    bm25_shared = BM25Chunk(id=9, document_id=1, chunk_index=0, text="shared", score=3.0)

    monkeypatch.setattr(
        "app.services.hybrid_retrieval.retrieve",
        lambda db, tenant_id, question, top_k: [shared],
    )
    monkeypatch.setattr(
        "app.services.hybrid_retrieval.bm25_retrieve",
        lambda db, tenant_id, question, top_k: [bm25_shared],
    )

    results = hybrid_retrieve(db=None, tenant_id=1, question="irrelevant", top_k=10)

    assert len(results) == 1
    assert results[0].rrf_score == 1 / 61 + 1 / 61
