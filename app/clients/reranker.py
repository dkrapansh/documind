from app.config import settings
from app.schemas.query import FusedChunk

_model = None

def _get_model():
    """Lazy singleton - sentence_transformers pulls in torch, which costs
    a few hundred MB just to import, before a model is even loaded.
    Deferring this to first real use (instead of import time) is what
    lets the app boot and answer /health inside Render free tier's 512MB
    ceiling; a request that never reranks never pays for it."""
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(settings.reranker_model)
    return _model

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
    """
    pairs = [(question, chunk.text) for chunk in chunks]
    scores = _get_model().predict(pairs)
    return sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
