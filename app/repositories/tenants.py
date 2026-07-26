from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from app.models.tenant import Tenant

def create_tenant(db: Session, name: str, is_ephemeral: bool = False) -> Tenant:
    tenant = Tenant(name=name, is_ephemeral=is_ephemeral)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

def get_by_name(db: Session, name: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.name == name).first()

def get_expired_ephemeral(db: Session, ttl_minutes: int) -> list[Tenant]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
    return (
        db.query(Tenant)
        .filter(Tenant.is_ephemeral.is_(True), Tenant.created_at < cutoff)
        .all()
    )

def delete(db: Session, tenant_id: int) -> None:
    db.query(Tenant).filter(Tenant.id == tenant_id).delete()