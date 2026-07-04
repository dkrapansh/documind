from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.api_keys import create_api_key
from app.repositories.tenants import create_tenant
from app.schemas.auth import CreateKeyRequest, CreateKeyResponse

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/keys", response_model=CreateKeyResponse)
def issue_key(payload: CreateKeyRequest, db: Session = Depends(get_db)):
    tenant = create_tenant(db, name=payload.tenant_name)
    _, raw_key = create_api_key(db, tenant_id = tenant.id)
    return CreateKeyResponse(api_key=raw_key, tenant_id=tenant.id)