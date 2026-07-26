from datetime import datetime, timezone
from sqlalchemy import Boolean, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    # True for tenants minted by the frontend proxy's per-visitor demo
    # session (app/api/routers/auth.py's /auth/demo-session) - these are
    # swept once they age past settings.ephemeral_tenant_ttl_minutes so
    # the shared public demo never accumulates one visitor's uploads
    # where another visitor's queries could retrieve them.
    is_ephemeral: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )