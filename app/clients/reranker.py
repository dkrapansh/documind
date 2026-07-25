from app.config import settings
from app.schemas.query import FusedChunk

_ranker = None

def _get_ranker():
    """Lazy singleton, same reasoning as the CrossEncoder this replaced:
    deferring the model load until first use is what lets /health boot
    without paying for it. flashrank's ONNX runtime has no PyTorch-sized
    framework tax, but the lazy pattern stays anyway so a request that
    never reranks still never pays for the smaller ONNX load either."""
    global _ranker
    if _ranker is None:
        from flashrank import Ranker
        _ranker = Ranker(model_name=settings.reranker_model)
    return _ranker

def rerank_chunks(question: str, chunks: list[FusedChunk]) -> list[tuple[FusedChunk, float]]:
    """Scores each candidate chunk against the question with a real
    cross-encoder (question and chunk encoded together, one forward
    pass per pair) rather than a bi-encoder compared by distance.
    Cross-encoders are far more accurate at judging relevance, too
    slow for a whole corpus but cheap over the small candidate set
    RRF narrows to.

    Runs locally, no network call once the model is cached, so this
    step is unaffected by API quota.

    flashrank's scores are sigmoid/softmax [0, 1], not the old
    CrossEncoder's raw logits (~-11 to +5.6), which is why
    confidence_threshold moved to 0.7 (see eval/RESULTS.md).
    """
    from flashrank import RerankRequest

    passages = [{"id": chunk.id, "text": chunk.text} for chunk in chunks]
    results = _get_ranker().rerank(RerankRequest(query=question, passages=passages))

    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    scored = [(chunks_by_id[result["id"]], float(result["score"])) for result in results]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)
