from pydantic import BaseModel

class CreateKeyRequest(BaseModel):
    tenant_name: str

class CreateKeyResponse(BaseModel):
    api_key: str
    tenant_id: int