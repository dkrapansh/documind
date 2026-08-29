import logging
import time
import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import GenerationFailedException
from app.repositories.query_logs import create_query_log
from app.schemas.query import QueryResponse, RetrievedChunk
from app.services.answering import REFUSAL_ANSWER, answer_question
from app.services.query_cache import get_cached_answer, set_cached_answer
from app.services.reranking import retrieve_ranked

logger = logging.getLogger(__name__)

GENERATION_FAILURE_ANSWER = (
    "Something went wrong while generating an answer. Please try again."
)


def resolve_session_id(session_id: str | None) -> str:
    """First call of a conversation gets a minted session_id; the caller
    sends it back on follow-ups so history groups by session, not by
    individual request."""
    return session_id or str(uuid.uuid4())


def log_query(
    db: Session,
    tenant_id: int,
    session_id: str,
    question: str,
    chunks: list[RetrievedChunk],
    answer: str,
    confidence: float | None,
    started_at: float,
    correlation_id: str,
) -> None:
    """Shared by both the non-streaming and SSE query paths, so latency
    is always measured the same way (perf_counter at request start to
    the moment the answer - streamed or not - is fully known)."""
    create_query_log(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        question=question,
        retrieved_chunk_ids=[chunk.id for chunk in chunks],
        answer=answer,
        confidence=confidence,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        correlation_id=correlation_id,
    )


def answer_query(
    db: Session,
    tenant_id: int,
    question: str,
    session_id: str | None,
    correlation_id: str,
) -> QueryResponse:
    """The full POST /query flow: cache-aside, then on a miss, hybrid
    retrieval, the refusal gate, and generation, then a query-log write.
    The one place this orchestration lives, so the router just
    translates HTTP in and out.

    A generation failure is caught here instead of propagating as an
    unhandled 500: it's still logged, never cached (a transient failure
    shouldn't poison repeat questions), and surfaces as a clean 503.
    """
    started_at = time.perf_counter()
    resolved_session_id = resolve_session_id(session_id)

    cached = get_cached_answer(tenant_id, question)
    if cached is not None:
        log_query(
            db, tenant_id, resolved_session_id, question, cached.sources, cached.answer,
            cached.confidence, started_at, correlation_id,
        )
        return QueryResponse(
            question=question, answer=cached.answer, sources=cached.sources,
            session_id=resolved_session_id,
        )

    chunks = retrieve_ranked(db, tenant_id, question)
    if not chunks:
        answer, confidence = REFUSAL_ANSWER, None
        set_cached_answer(tenant_id, question, answer, chunks, confidence)
        log_query(
            db, tenant_id, resolved_session_id, question, chunks, answer, confidence,
            started_at, correlation_id,
        )
        return QueryResponse(
            question=question, answer=answer, sources=chunks, session_id=resolved_session_id
        )

    confidence = chunks[0].confidence
    try:
        answer = answer_question(question, chunks).answer
        if not answer:
            raise ValueError("generation returned an empty answer")
        # The model, not a score threshold, decides whether the context
        # actually answers the question (see services/reranking.py). When it
        # refuses, drop the retrieved chunks: they were candidates the model
        # judged insufficient, and showing them as sources under a refusal
        # would cite documents as support for an answer that was never given.
        if answer.strip() == REFUSAL_ANSWER:
            chunks = []
            confidence = None
    except Exception:
        logger.exception(
            "query_service.answer_query: generation failed for tenant %s", tenant_id
        )
        log_query(
            db, tenant_id, resolved_session_id, question, chunks, GENERATION_FAILURE_ANSWER,
            confidence, started_at, correlation_id,
        )
        raise GenerationFailedException()

    set_cached_answer(tenant_id, question, answer, chunks, confidence)
    log_query(
        db, tenant_id, resolved_session_id, question, chunks, answer, confidence,
        started_at, correlation_id,
    )
    return QueryResponse(
        question=question, answer=answer, sources=chunks, session_id=resolved_session_id
    )
