from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.db.base import Base

class Chunk(Base):
    __tablename__ = "chunks"

    # A document's chunk_index is its natural key, so the database refuses a
    # duplicate rather than trusting ingestion never to insert one twice.
    # This is what actually makes a retry safe: re-running a job deletes this
    # document's chunks and re-inserts them, and if that delete were ever
    # missed the insert fails loudly instead of silently doubling every
    # chunk, which would distort BM25 term statistics, let RRF fuse a chunk
    # with itself, and let the same text occupy several slots in the final
    # top-4 context.
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_id_chunk_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(String)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))
    token_count: Mapped[int] = mapped_column(Integer, default=0)