from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, Float, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    session_id: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(String)
    retrieved_chunk_ids: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[float] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )