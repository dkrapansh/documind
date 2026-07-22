from sqlalchemy.orm import Session
from app.models.tenant import Tenant

def create_tenant(db: Session, name: str) -> Tenant:
    tenant = Tenant(name=name)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant

def get_by_name(db: Session, name: str) -> Tenant | None:
    return db.query(Tenant).filter(Tenant.name == name).first()