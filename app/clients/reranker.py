import logging
import threading

from app.config import settings
from app.core.exceptions import RerankerUnavailableException
from app.schemas.query import FusedChunk

logger = logging.getLogger(__name__)

_ranker = None
# The first request to reach reranking triggers a model load that may involve
# a download. Without this lock, several concurrent first-requests each start
# their own load: several downloads of the same file into the same cache
# directory, several copies of the model in memory at once, on a host with a
# 512MB ceiling. One thread loads, the rest wait for it.
_ranker_lock = threading.Lock()


def _get_ranker():
    """Lazy singleton, same reasoning as the CrossEncoder this replaced:
    deferring the model load until first use is what lets the app boot
    without paying for it. flashrank's ONNX runtime has no PyTorch-sized
    framework tax, but the lazy pattern stays anyway so a request that never
    reranks still never pays for the smaller ONNX load either.

    The cost of loading lazily is that the load happens inside a user's
    request. On a cold instance the model is not in the cache yet, so that
    first request pays for a download from a CDN this code does not control.
    A slow or unreachable CDN used to stall that request indefinitely: there
    was no timeout, and any failure surfaced as an unhandled 500 with the
    real cause buried in a traceback.
    """
    global _ranker
    if _ranker is not None:
        return _ranker

    with _ranker_lock:
        # Re-check inside the lock: another thread may have finished loading
        # while this one waited.
        if _ranker is not None:
            return _ranker
        try:
            from flashrank import Ranker

            logger.info(
                "loading reranker model", extra={"model": settings.reranker_model}
            )
            _ranker = Ranker(model_name=settings.reranker_model)
            logger.info("reranker model ready", extra={"model": settings.reranker_model})
        except Exception as exc:
            # Left as None so a later request can retry: a CDN outage or a
            # half-written cache file is usually transient, and permanently
            # poisoning the singleton would turn a temporary failure into one
            # that lasts until the next deploy.
            _ranker = None
            logger.exception(
                "reranker model failed to load",
                extra={"model": settings.reranker_model, "error_type": type(exc).__name__},
            )
            raise RerankerUnavailableException()
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

    The score orders candidates and nothing more. It is not compared against
    a threshold to decide whether to answer: see services/reranking.py for
    the measurements that removed that gate.
    """
    from flashrank import RerankRequest

    passages = [{"id": chunk.id, "text": chunk.text} for chunk in chunks]
    try:
        results = _get_ranker().rerank(RerankRequest(query=question, passages=passages))
    except RerankerUnavailableException:
        raise
    except Exception as exc:
        # Scoring itself failed on a loaded model, which is a different
        # failure from the model being unavailable, but the caller can do
        # nothing different about it and a bare 500 tells nobody anything.
        logger.exception(
            "reranking failed",
            extra={"candidates": len(chunks), "error_type": type(exc).__name__},
        )
        raise RerankerUnavailableException()

    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    scored = [(chunks_by_id[result["id"]], float(result["score"])) for result in results]
    return sorted(scored, key=lambda pair: pair[1], reverse=True)
