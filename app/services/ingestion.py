import logging

from app.clients.embeddings import embed_text
from app.config import settings
from app.db.session import SessionLocal
from app.repositories.chunks import create_chunks, delete_by_document
from app.repositories.document_contents import get_text
from app.repositories.documents import (
    get_by_id,
    mark_failed,
    mark_ready,
    release_for_retry,
)
from app.services.chunking import chunk_text, count_tokens
from app.services.query_cache import bump_scope

logger = logging.getLogger(__name__)


class PermanentIngestionError(Exception):
    """A failure that retrying cannot fix: no extractable text, or a document
    too large to embed within the configured budget. Distinguished from a
    transient failure (an embedding provider timing out) because retrying the
    latter is useful and retrying the former just burns attempts and quota
    before failing anyway.
    """


def process_document(document_id: int) -> None:
    """Run one claimed ingestion job to a terminal state, or hand it back for
    another attempt.

    The caller (services/ingestion_worker.py) has already claimed this job by
    setting status to processing, incrementing attempt_count, and taking a
    lease. This function's contract is that the job never silently stops: it
    ends at ready, at failed with a reason, or back at pending for a retry.
    If the process dies before any of those, the lease expires and recovery
    requeues it.

    Runs in its own DB session because the worker thread has no request
    session to borrow.
    """
    db = SessionLocal()
    document = None
    try:
        document = get_by_id(db, document_id)
        if document is None:
            logger.error("process_document: document not found", extra={"document_id": document_id})
            return

        tenant_id = document.tenant_id
        extracted_text = get_text(db, document_id)
        if extracted_text is None:
            raise PermanentIngestionError(
                "No extracted text is stored for this document. Please re-upload it."
            )

        raw_chunks = chunk_text(extracted_text)
        if not raw_chunks:
            raise PermanentIngestionError(
                "No readable text could be extracted from this document. "
                "If it is a scanned PDF, it has no text layer and needs OCR, which is not supported."
            )

        # Bounds embedding spend per upload. The 20MB upload cap limits bytes,
        # not work: a large text file produces thousands of chunks, each one a
        # separate paid embedding call with its own retries, so without this a
        # single upload could consume a whole day's quota.
        if len(raw_chunks) > settings.max_chunks_per_document:
            raise PermanentIngestionError(
                f"Document produces {len(raw_chunks)} chunks, over the limit of "
                f"{settings.max_chunks_per_document}. Please split it into smaller documents."
            )

        chunk_rows = []
        for index, piece in enumerate(raw_chunks):
            embedding = embed_text(piece)
            chunk_rows.append(
                {
                    "index": index,
                    "text": piece,
                    "embedding": embedding,
                    "token_count": count_tokens(piece),
                }
            )

        # Idempotency. A retry must replace this document's chunks, not add a
        # second copy of them: duplicated chunks distort BM25 term statistics,
        # let RRF fuse a chunk with itself, and let the same text occupy
        # several slots in the final top-4 context. The unique constraint on
        # (document_id, chunk_index) is the backstop if this delete is ever
        # missed, turning a silent corruption into a loud failure.
        delete_by_document(db, document_id, tenant_id)
        create_chunks(db, document_id, tenant_id, chunk_rows)
        mark_ready(db, document_id, chunk_count=len(chunk_rows))
        # One commit for the chunks and the ready flip together, so a document
        # is never queryable before its chunks exist.
        db.commit()
        bump_scope(tenant_id)

        logger.info(
            "ingestion complete",
            extra={
                "document_id": document_id,
                "tenant_id": tenant_id,
                "chunk_count": len(chunk_rows),
                "attempt": document.attempt_count,
            },
        )

    except PermanentIngestionError as exc:
        db.rollback()
        logger.warning(
            "ingestion failed permanently",
            extra={"document_id": document_id, "reason": str(exc)},
        )
        mark_failed(db, document_id, str(exc))
        if document is not None:
            bump_scope(document.tenant_id)

    except Exception as exc:
        db.rollback()
        # Transient by assumption: an embedding timeout, a rate limit, a
        # dropped database connection. Hand the job back so another attempt
        # can take it, unless attempts are exhausted. attempt_count already
        # incremented when the job was claimed, so this cannot loop forever.
        attempts = document.attempt_count if document is not None else settings.ingestion_max_attempts
        exhausted = attempts >= settings.ingestion_max_attempts

        logger.exception(
            "ingestion attempt failed",
            extra={
                "document_id": document_id,
                "attempt": attempts,
                "error_type": type(exc).__name__,
                "will_retry": not exhausted,
            },
        )

        reason = f"Ingestion failed ({type(exc).__name__}). "
        if exhausted:
            mark_failed(db, document_id, reason + "Retry limit reached. Re-upload to try again.")
            if document is not None:
                bump_scope(document.tenant_id)
        else:
            release_for_retry(db, document_id, reason + "Will retry automatically.")

    finally:
        db.close()
