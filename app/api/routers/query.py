import time
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.repositories.query_logs import create_query_log
from app.schemas.query import QueryRequest, QueryResponse
from app.services.answering import answer_question
from app.services.reranking import retrieve_ranked

router = APIRouter(prefix="/query", tags=["query"])

REFUSAL_ANSWER = (
    "I don't have enough relevant information in the uploaded documents "
    "to answer that question confidently."
)


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

    chunks = retrieve_ranked(db, tenant_id, body.question)
    if not chunks:
        response = QueryResponse(question=body.question, answer=REFUSAL_ANSWER, sources=[])
    else:
        response = answer_question(body.question, chunks)
    response.session_id = session_id

    create_query_log(
        db,
        tenant_id=tenant_id,
        session_id=session_id,
        question=body.question,
        retrieved_chunk_ids=[chunk.id for chunk in chunks],
        answer=response.answer,
        confidence=chunks[0].confidence if chunks else None,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        correlation_id=request.state.correlation_id,
    )

    return response
