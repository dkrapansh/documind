import json
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.db.session import SessionLocal
from app.repositories.query_logs import create_query_log
from app.schemas.query import QueryRequest, QueryResponse
from app.services.answering import REFUSAL_ANSWER, answer_question, stream_answer_question
from app.services.query_cache import get_cached_answer, set_cached_answer
from app.services.reranking import retrieve_ranked

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse, dependencies=[Depends(api_key_header)])
async def query_documents(
    body: QueryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id
    started_at = time.perf_counter()

    # First call of a conversation gets a minted session_id; the caller
    # sends it back on follow-ups so history groups by session, not by
    # individual request.
    session_id = body.session_id or str(uuid.uuid4())

    # Cache-aside: a hit skips retrieval (embedding + BM25 + rerank) and the
    # LLM call entirely. Keyed on (tenant, normalized question, doc-scope
    # version) - see services/query_cache.py for why session_id is never
    # part of what's cached.
    cached = get_cached_answer(tenant_id, body.question)
    if cached is not None:
        chunks = cached.sources
        answer = cached.answer
        confidence = cached.confidence
    else:
        chunks = retrieve_ranked(db, tenant_id, body.question)
        if not chunks:
            answer = REFUSAL_ANSWER
            confidence = None
        else:
            answer = answer_question(body.question, chunks).answer
            confidence = chunks[0].confidence
        set_cached_answer(tenant_id, body.question, answer, chunks, confidence)

    response = QueryResponse(
        question=body.question, answer=answer, sources=chunks, session_id=session_id
    )

    create_query_log(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        question=body.question,
        retrieved_chunk_ids=[chunk.id for chunk in chunks],
        answer=answer,
        confidence=confidence,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        correlation_id=request.state.correlation_id,
    )

    return response


def _log_streamed_query(
    tenant_id: int,
    session_id: str,
    question: str,
    retrieved_chunk_ids: list[int],
    accumulated_answer: list[str],
    confidence: float | None,
    started_at: float,
    correlation_id: str,
) -> None:
    """Runs as a StreamingResponse `background` task - i.e. only after
    the whole SSE body has finished sending, so accumulated_answer (the
    same list object event_stream() appended each delta to) is guaranteed
    fully populated and latency can be measured end-to-end, by this
    point. Opens its OWN session, same reasoning as
    services/ingestion.py's process_document: the request's own
    Depends(get_db) session is torn down once the response starts
    streaming, well before this runs.
    """
    db = SessionLocal()
    try:
        create_query_log(
            db,
            tenant_id=tenant_id,
            session_id=session_id,
            question=question,
            retrieved_chunk_ids=retrieved_chunk_ids,
            answer="".join(accumulated_answer),
            confidence=confidence,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            correlation_id=correlation_id,
        )
    finally:
        db.close()


@router.get("/stream", dependencies=[Depends(api_key_header)])
async def query_documents_stream(
    question: str,
    request: Request,
    db: Session = Depends(get_db),
    session_id: str | None = None,
):
    """SSE variant of POST /query: retrieval happens up front exactly like
    the non-streaming path (it's already fast and doesn't benefit from
    streaming), but the answer is forwarded to the client token-by-token
    as Gemini generates it, instead of waiting for the complete answer.

    A GET (not POST) endpoint is deliberate, not a REST-purity choice:
    the browser's native EventSource API - the standard SSE client - can
    only ever issue GET requests with no custom body, so params travel as
    a query string instead of a JSON body like QueryRequest.
    """
    tenant_id = request.state.tenant_id
    correlation_id = request.state.correlation_id
    started_at = time.perf_counter()
    resolved_session_id = session_id or str(uuid.uuid4())

    chunks = retrieve_ranked(db, tenant_id, question)
    accumulated_answer: list[str] = []

    def event_stream():
        sources_payload = [
            {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
        yield f"event: sources\ndata: {json.dumps(sources_payload)}\n\n"
        yield f"event: session\ndata: {json.dumps({'session_id': resolved_session_id})}\n\n"

        if not chunks:
            accumulated_answer.append(REFUSAL_ANSWER)
            yield f"event: delta\ndata: {json.dumps({'text': REFUSAL_ANSWER})}\n\n"
        else:
            for delta in stream_answer_question(question, chunks):
                accumulated_answer.append(delta)
                yield f"event: delta\ndata: {json.dumps({'text': delta})}\n\n"

        yield "event: done\ndata: {}\n\n"

    log_task = BackgroundTask(
        _log_streamed_query,
        tenant_id=tenant_id,
        session_id=resolved_session_id,
        question=question,
        retrieved_chunk_ids=[chunk.id for chunk in chunks],
        accumulated_answer=accumulated_answer,
        confidence=chunks[0].confidence if chunks else None,
        started_at=started_at,
        correlation_id=correlation_id,
    )

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", background=log_task
    )
