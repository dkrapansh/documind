from app.schemas.query import FusedChunk
from app.services.reranking import retrieve_ranked

# Scores here use flashrank's real [0, 1] scale and the real 0.7
# threshold - they used to be on the old CrossEncoder's raw-logit scale,
# which stopped meaning anything once flashrank replaced it (see
# eval/RESULTS.md). The real end-to-end boundary is covered by
# test_retrieval.py's test_retrieve_ranked_refuses_when_no_chunk_is_actually_relevant;
# these stay unit-level to isolate retrieve_ranked's own slicing and
# threshold logic.

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
        lambda question, chunks: [(chunks[0], 0.95), (chunks[1], 0.88), (chunks[2], 0.75)],
    )
    monkeypatch.setattr("app.services.reranking.settings.confidence_threshold", 0.7)

    results = retrieve_ranked(db=None, tenant_id=1, question="irrelevant")

    assert [chunk.id for chunk in results] == [1, 2, 3]
    assert results[0].confidence == 0.95

def test_retrieve_ranked_refuses_when_best_score_is_below_threshold(monkeypatch):
    candidates = [_fused_chunk(1, "a")]
    monkeypatch.setattr(
        "app.services.reranking.hybrid_retrieve",
        lambda db, tenant_id, question, top_k: candidates,
    )
    monkeypatch.setattr(
        "app.services.reranking.rerank_chunks",
        lambda question, chunks: [(chunks[0], 0.3)],
    )
    monkeypatch.setattr("app.services.reranking.settings.confidence_threshold", 0.7)

    results = retrieve_ranked(db=None, tenant_id=1, question="irrelevant")

    assert results == []

def test_retrieve_ranked_refuses_when_no_candidates_found(monkeypatch):
    monkeypatch.setattr(
        "app.services.reranking.hybrid_retrieve",
        lambda db, tenant_id, question, top_k: [],
    )

    results = retrieve_ranked(db=None, tenant_id=1, question="irrelevant")

    assert results == []
