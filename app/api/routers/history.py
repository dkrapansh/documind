from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.repositories.query_logs import list_by_session
from app.schemas.query import QueryLogResponse

router = APIRouter(prefix="/history", tags=["history"])


@router.get(
    "/{session_id}",
    response_model=list[QueryLogResponse],
    dependencies=[Depends(api_key_header)],
)
async def get_session_history(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = request.state.tenant_id
    return list_by_session(db, tenant_id, session_id)
