from pydantic import BaseModel, Field

# Matches tenants.name's String(255) column - an unbounded string here
# would let a caller insert an arbitrarily large row before anything
# else validates it.
MAX_TENANT_NAME_LENGTH = 255

class CreateKeyRequest(BaseModel):
    tenant_name: str = Field(min_length=1, max_length=MAX_TENANT_NAME_LENGTH)

class CreateKeyResponse(BaseModel):
    api_key: str
    tenant_id: int

class GoogleLoginRequest(BaseModel):
    id_token: str = Field(min_length=1)