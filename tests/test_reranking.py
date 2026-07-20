from app.schemas.query import FusedChunk
from app.services.reranking import retrieve_ranked

def _fused_chunk(chunk_id: int, text: str) -> FusedChunk:
    return FusedChunk(id=chunk_id, document_id=1, chunk_index=0, text=text, rrf_score=0.01)

def test_retrieve_ranked_returns_top_ranked_chunks_when_confidence_is_high(monkeypatch):
    candidates = [_fused_chunk(1, "a"), _fused_chunk(2, "b"), _fused_chunk(3, "c")]
    monkeypatch.setattr(
        "app.services.reranking.hybrid_retrieve",
        lambda db, tenant_id, question, top_k: candidates,
    )
    monkeypatch.setattr(
        "app.services.reranking.rerank_chunks",
        lambda question, chunks: [(chunks[0], 5.0), (chunks[1], 2.0), (chunks[2], -1.0)],
    )
    monkeypatch.setattr("app.services.reranking.settings.confidence_threshold", -6.0)

    results = retrieve_ranked(db=None, tenant_id=1, question="irrelevant")

    assert [chunk.id for chunk in results] == [1, 2, 3]
    assert results[0].confidence == 5.0

def test_retrieve_ranked_refuses_when_best_score_is_below_threshold(monkeypatch):
    candidates = [_fused_chunk(1, "a")]
    monkeypatch.setattr(
        "app.services.reranking.hybrid_retrieve",
        lambda db, tenant_id, question, top_k: candidates,
    )
    monkeypatch.setattr(
        "app.services.reranking.rerank_chunks",
        lambda question, chunks: [(chunks[0], -20.0)],
    )
    monkeypatch.setattr("app.services.reranking.settings.confidence_threshold", -6.0)

    results = retrieve_ranked(db=None, tenant_id=1, question="irrelevant")

    assert results == []

def test_retrieve_ranked_refuses_when_no_candidates_found(monkeypatch):
    monkeypatch.setattr(
        "app.services.reranking.hybrid_retrieve",
        lambda db, tenant_id, question, top_k: [],
    )

    results = retrieve_ranked(db=None, tenant_id=1, question="irrelevant")

    assert results == []
