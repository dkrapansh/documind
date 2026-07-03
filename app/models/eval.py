from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Float, Integer, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"))
    dataset_version: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    eval_run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"))
    question: Mapped[str] = mapped_column(String)
    faithfulness: Mapped[float] = mapped_column(Float, nullable=True)
    answer_relevancy: Mapped[float] = mapped_column(Float, nullable=True)
    context_precision: Mapped[float] = mapped_column(Float, nullable=True)