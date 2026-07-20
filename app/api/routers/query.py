from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.schemas.query import QueryRequest, QueryResponse
from app.services.answering import answer_question
from app.services.retrieval import retrieve

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse, dependencies=[Depends(api_key_header)])
async def query_documents(
    body: QueryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id

    chunks = retrieve(db, tenant_id, body.question)
    return answer_question(body.question, chunks)
