from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Integer, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

# The ingestion job's state machine, stored on the document itself rather
# than in a separate jobs table: there is exactly one ingestion job per
# document, so a separate table would only add a join.
#
#   PENDING -> PROCESSING -> READY
#                         -> PENDING   (retryable failure, attempts left)
#                         -> FAILED    (permanent, or attempts exhausted)
STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

TERMINAL_STATUSES = (STATUS_READY, STATUS_FAILED)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_PENDING)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    upload_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Ingestion job bookkeeping. Before these existed, a job lived only as a
    # closure inside FastAPI's BackgroundTasks, so a process restart mid-job
    # left the document at "processing" forever with nothing recording that
    # the work had ever started, who owned it, or why it stopped.
    #
    # attempt_count increments when a worker claims the job, not when it
    # finishes, so a worker that dies without ever reporting back still
    # burns an attempt and cannot loop forever.
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A lease, not a lock. The claiming worker owns this job until this time
    # passes; after that any worker (including one on a fresh instance after
    # a crash) may reclaim it. This is what makes a stranded job recoverable
    # without a coordinator.
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Why the last attempt failed, in language safe to show the uploader.
    # "failed" alone cannot distinguish a scanned PDF from a corrupt file
    # from an embedding provider outage, which are three different user
    # actions.
    error_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)