from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from app.models.tenant import Tenant

def create_tenant(db: Session, name: str, is_ephemeral: bool = False) -> Tenant:
    """Always inserts, even on a repeated name - intentional, not a bug.
    tenant_name is unauthenticated (POST /auth/keys has no prior
    credential to check), so a get-or-create here would let anyone
    guess another tenant's name and walk off with a fresh key into its
    data. Two callers picking the same name just get two isolated
    tenants instead. Code that legitimately needs to reuse one tenant
    (the eval harness) does its own get-or-create against a fixed
    internal name - see evaluation.py's _ensure_eval_tenant.
    """
    tenant = Tenant(name=name, is_ephemeral=is_ephemeral)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

def get_by_name(db: Session, name: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.name == name).first()

def get_by_id(db: Session, tenant_id: int) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.id == tenant_id).first()

def get_expired_ephemeral(db: Session, ttl_minutes: int) -> list[Tenant]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
    return (
        db.query(Tenant)
        .filter(Tenant.is_ephemeral.is_(True), Tenant.created_at < cutoff)
        .all()
    )

def delete(db: Session, tenant_id: int) -> None:
    db.query(Tenant).filter(Tenant.id == tenant_id).delete()