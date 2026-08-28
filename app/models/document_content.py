from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentContent(Base):
    """Extracted plain text for one document, held in Postgres.

    Uploaded files used to be written to the container's local disk and read
    back by the background job. On Render that disk is ephemeral, so any
    restart between upload and ingestion destroyed the bytes: the job could
    never succeed, and no retry could ever fix it because the input was gone.
    Storing the extracted text in the same transactional store as the
    document row means a restart loses nothing and a retry has everything it
    needs.

    A separate table rather than a column on documents, because
    GET /documents lists a tenant's documents on every demo page load and
    would otherwise drag the full text of every document across the wire for
    a response that only shows filenames and statuses.

    The tradeoff, recorded honestly: the original bytes are no longer kept,
    so re-extracting with a better parser (or adding OCR later) requires a
    re-upload. Extraction happens in the upload request now, which also means
    a corrupt or text-free file fails immediately with a real error instead
    of landing in "failed" minutes later with no reason attached.
    """

    __tablename__ = "document_contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Unique: one extraction per document. Also the natural upsert key when a
    # document is re-ingested.
    document_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id"), unique=True, index=True
    )
    text: Mapped[str] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
