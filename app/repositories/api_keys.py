from sqlalchemy.orm import Session

from app.core.security import generate_api_key, hash_key
from app.models.api_key import ApiKey

def create_api_key(db: Session, tenant_id: int) -> tuple[ApiKey, str]:
    raw_key = generate_api_key()
    api_key = ApiKey(tenant_id = tenant_id, hashed_key = hash_key(raw_key))
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, raw_key

def het_by_hashed_key(db: Session, hashed_key: str) -> ApiKey | None:
    return db.query(ApiKey).filter(
        ApiKey.hashed_key == hashed_key, ApiKey.revoked.is_(False)
    ).first()