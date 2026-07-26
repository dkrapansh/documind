from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_scheme import api_key_header
from app.repositories.api_keys import create_api_key, revoke
from app.repositories.tenants import create_tenant
from app.schemas.auth import CreateKeyRequest, CreateKeyResponse

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/keys", response_model=CreateKeyResponse)
def issue_key(payload: CreateKeyRequest, db: Session = Depends(get_db)):
    tenant = create_tenant(db, name=payload.tenant_name)
    _, raw_key = create_api_key(db, tenant_id = tenant.id)
    return CreateKeyResponse(api_key=raw_key, tenant_id=tenant.id)

@router.post("/keys/revoke", status_code=204, dependencies=[Depends(api_key_header)])
def revoke_key(request: Request, db: Session = Depends(get_db)):
    """Self-revoke: the caller can only revoke the key it authenticated
    with, not an arbitrary key ID - there's no cross-tenant key lookup
    exposed here on purpose."""
    revoke(db, request.state.api_key_id)
    return Response(status_code=204)