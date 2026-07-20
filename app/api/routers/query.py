from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
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

    chunks = retrieve_ranked(db, tenant_id, body.question)
    if not chunks:
        return QueryResponse(question=body.question, answer=REFUSAL_ANSWER, sources=[])

    return answer_question(body.question, chunks)
