import json
import logging
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.db.session import SessionLocal
from app.schemas.query import MAX_QUESTION_LENGTH, QueryRequest, QueryResponse
from app.services.answering import REFUSAL_ANSWER, stream_answer_question
from app.services.query_cache import get_cached_answer, set_cached_answer
from app.services.query_service import (
    GENERATION_FAILURE_ANSWER,
    answer_query,
    log_query,
    resolve_session_id,
)
from app.services.reranking import retrieve_ranked

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse, dependencies=[Depends(api_key_header)])
async def query_documents(
    body: QueryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    return answer_query(
        db,
        tenant_id=request.state.tenant_id,
        question=body.question,
        session_id=body.session_id,
        correlation_id=request.state.correlation_id,
    )


def _log_streamed_query(
    tenant_id: int,
    session_id: str,
    question: str,
    chunks: list,
    accumulated_answer: list[str],
    confidence: float | None,
    started_at: float,
    correlation_id: str,
    cached_hit: bool,
    failure: dict,
) -> None:
    """Runs as a StreamingResponse `background` task, after the SSE body
    finishes sending, same as ingestion.py's process_document: the
    request's own session is torn down once streaming starts.

    failure is a dict, not a bool, since BackgroundTask binds kwargs at
    construction time, before the generator runs - a plain bool would
    always read False. Skips caching on a cache replay or a generation
    failure, mirroring answer_query's non-streaming cache-aside rules.
    """
    full_answer = "".join(accumulated_answer)
    if not cached_hit and not failure["happened"]:
        set_cached_answer(tenant_id, question, full_answer, chunks, confidence)

    db = SessionLocal()
    try:
        log_query(
            db, tenant_id, session_id, question, chunks, full_answer,
            confidence, started_at, correlation_id,
        )
    finally:
        db.close()


@router.get("/stream", dependencies=[Depends(api_key_header)])
async def query_documents_stream(
    request: Request,
    question: str = Query(min_length=1, max_length=MAX_QUESTION_LENGTH),
    db: Session = Depends(get_db),
    session_id: str | None = None,
):
    """SSE variant of POST /query: cache-aside up front like the
    non-streaming path; on a miss, retrieval happens up front too, but
    the answer streams to the client token by token as Gemini generates it.

    GET instead of POST is deliberate: the browser's native EventSource
    API can only issue GET with no body, so params travel as a query
    string instead of a JSON body.
    """
    tenant_id = request.state.tenant_id
    correlation_id = request.state.correlation_id
    started_at = time.perf_counter()
    resolved_session_id = resolve_session_id(session_id)

    cached = get_cached_answer(tenant_id, question)
    chunks = cached.sources if cached is not None else retrieve_ranked(db, tenant_id, question)
    confidence = cached.confidence if cached is not None else (chunks[0].confidence if chunks else None)

    accumulated_answer: list[str] = []
    failure = {"happened": False}

    def event_stream():
        sources_payload = [
            {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "confidence": chunk.confidence,
            }
            for chunk in chunks
        ]
        yield f"event: sources\ndata: {json.dumps(sources_payload)}\n\n"
        yield f"event: session\ndata: {json.dumps({'session_id': resolved_session_id})}\n\n"

        if cached is not None:
            accumulated_answer.append(cached.answer)
            yield f"event: delta\ndata: {json.dumps({'text': cached.answer})}\n\n"
        elif not chunks:
            accumulated_answer.append(REFUSAL_ANSWER)
            yield f"event: delta\ndata: {json.dumps({'text': REFUSAL_ANSWER})}\n\n"
        else:
            try:
                for delta in stream_answer_question(question, chunks):
                    accumulated_answer.append(delta)
                    yield f"event: delta\ndata: {json.dumps({'text': delta})}\n\n"
            except Exception:
                # A dropped connection or a Gemini failure mid-stream both
                # land here. Without this, the generator would just stop -
                # no "done" event, a truncated answer logged as if it were
                # complete, and the client left hanging with no signal it
                # failed (see query_service.answer_query for the
                # equivalent non-streaming 503 path this mirrors).
                logger.exception(
                    "query_documents_stream: generation failed mid-stream for tenant %s",
                    tenant_id,
                )
                failure["happened"] = True
                accumulated_answer.clear()
                accumulated_answer.append(GENERATION_FAILURE_ANSWER)
                yield f"event: error\ndata: {json.dumps({'message': GENERATION_FAILURE_ANSWER})}\n\n"

        # The model, not a score threshold, decides whether to refuse (see
        # services/reranking.py). Sources are streamed before generation
        # starts, deliberately, so the client can show them while the answer
        # types out. That means a refusal cannot simply omit them the way the
        # non-streaming path does. Instead the done event reports whether
        # this turned out to be a refusal, so the client can drop the sources
        # it was shown rather than leave documents displayed as support for
        # an answer that was never given.
        refused = "".join(accumulated_answer).strip() == REFUSAL_ANSWER
        yield f"event: done\ndata: {json.dumps({'refused': refused})}\n\n"

    log_task = BackgroundTask(
        _log_streamed_query,
        tenant_id=tenant_id,
        session_id=resolved_session_id,
        question=question,
        chunks=chunks,
        accumulated_answer=accumulated_answer,
        confidence=confidence,
        started_at=started_at,
        correlation_id=correlation_id,
        cached_hit=cached is not None,
        failure=failure,
    )

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", background=log_task
    )
