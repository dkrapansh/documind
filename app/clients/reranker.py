from app.config import settings
from app.schemas.query import FusedChunk

_ranker = None

def _get_ranker():
    """Lazy singleton - same reasoning as the CrossEncoder this replaced:
    deferring the model load to first real use (instead of import time) is
    what lets the app boot and answer /health without paying for it. Unlike
    the old CrossEncoder, flashrank runs on ONNX Runtime rather than
    PyTorch, so there's no ~500MB framework tax just to import it - but the
    lazy pattern is kept anyway so a request that never reranks still never
    pays even the smaller ONNX model load."""
    global _ranker
    if _ranker is None:
        from flashrank import Ranker
        _ranker = Ranker(model_name=settings.reranker_model)
    return _ranker

def rerank_chunks(question: str, chunks: list[FusedChunk]) -> list[tuple[FusedChunk, float]]:
    """Score each candidate chunk against the question with a real
    cross-encoder (question and chunk text encoded together, one forward
    pass per pair) rather than a bi-encoder (each encoded separately,
    compared by distance - what embeddings already do for dense
    retrieval). Cross-encoders see both texts at once, so they're far
    more accurate at judging relevance - too slow to run over a whole
    corpus, but cheap enough to run over the small candidate set RRF
    already narrowed things down to.

    Runs locally (no OpenAI call, no network dependency once the model
    is cached), so this step is unaffected by API quota.

    NOTE: flashrank's scores are sigmoid/softmax-normalized into roughly
    [0, 1] - NOT the old CrossEncoder's raw logits (~-11 to +5.6).
    settings.confidence_threshold (-3.0) was tuned against the old scale
    and needs retuning against this one. Deliberately not changed here.
    """
    from flashrank import RerankRequest

    passages = [{"id": chunk.id, "text": chunk.text} for chunk in chunks]
    results = _get_ranker().rerank(RerankRequest(query=question, passages=passages))

    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    scored = [(chunks_by_id[result["id"]], float(result["score"])) for result in results]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)
