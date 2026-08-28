from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.document import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING,
    Document,
)

def get_by_content_hash(db: Session, tenant_id: int, content_hash: str) -> Document | None:
    """Deduplication lookup for uploads.

    Deliberately excludes failed documents. It used to match any status, so
    re-uploading a file that had failed returned the failed row with HTTP
    200: the user was told the upload succeeded, then polled a document that
    would never become ready, with no way to retry it through the API at all.
    Excluding failed rows makes a re-upload the retry mechanism.
    """
    return db.query(Document).filter(
        Document.tenant_id == tenant_id,
        Document.content_hash == content_hash,
        Document.status != STATUS_FAILED,
    ).first()

def create_document(
        db: Session, tenant_id: int, filename: str, content_hash: str
) -> Document:
    document = Document(
        tenant_id = tenant_id,
        filename = filename,
        content_hash = content_hash,
        status = "pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document

def create_ready_document(
        db: Session, tenant_id: int, filename: str, content_hash: str, chunk_count: int
) -> Document:
    """Used only by the demo-seed cloner (services/demo_seed.py) - skips
    the pending/processing states because the chunks it's about to attach
    are copies of already-embedded ones, not freshly extracted text."""
    document = Document(
        tenant_id=tenant_id,
        filename=filename,
        content_hash=content_hash,
        status="ready",
        chunk_count=chunk_count,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document

def get_by_id(db: Session, document_id: int) -> Document | None:
    """Not tenant-scoped. Internal, trusted callers only: the ingestion
    worker looks up a document by an id it just claimed itself. Every
    API-facing lookup must use get_by_id_for_tenant instead."""
    return db.query(Document).filter(Document.id == document_id).first()


def claim_next_pending(db: Session, lease_seconds: int, max_attempts: int) -> int | None:
    """Atomically claim one pending ingestion job, or return None if there is
    nothing to do.

    The whole claim is a single UPDATE whose target is chosen by a
    SELECT ... FOR UPDATE SKIP LOCKED subquery. That combination is what
    makes this safe without any coordinator:

    - FOR UPDATE locks the candidate row, so two workers cannot select the
      same job.
    - SKIP LOCKED makes a second worker step over a row another worker has
      already locked and take the next one, instead of blocking behind it.
    - Doing it in one statement means there is no window between choosing a
      job and marking it claimed.

    attempt_count increments here, at claim time, not on completion. A worker
    that dies without ever reporting back has still burned an attempt, so a
    job that reliably kills its worker gets retried a bounded number of times
    and then stops, rather than looping forever.

    The lease is what makes a crash recoverable: the claimer owns this job
    only until lease_expires_at, after which recover_stale_jobs may hand it
    to someone else. See services/ingestion_worker.py for the loop that
    calls this.
    """
    now = datetime.now(timezone.utc)
    claimed_id = db.execute(
        text(
            """
            UPDATE documents
               SET status = :processing,
                   attempt_count = attempt_count + 1,
                   processing_started_at = :now,
                   lease_expires_at = :lease_expires_at
             WHERE id = (
                   SELECT id
                     FROM documents
                    WHERE status = :pending
                      AND attempt_count < :max_attempts
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
             )
         RETURNING id
            """
        ),
        {
            "processing": STATUS_PROCESSING,
            "pending": STATUS_PENDING,
            "now": now,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "max_attempts": max_attempts,
        },
    ).scalar_one_or_none()
    db.commit()
    return claimed_id


def recover_stale_jobs(db: Session, max_attempts: int) -> tuple[int, int]:
    """Return jobs whose lease has expired to the queue, or fail them if they
    have run out of attempts. Returns (requeued, failed).

    This is what stops a document from sitting at "processing" forever. A
    worker only holds a job for the length of its lease; if the process died,
    was redeployed, or was OOM-killed, the lease simply expires and the job
    becomes claimable again. No coordinator, no heartbeat protocol, and it
    works across a restart because the state is in the database rather than
    in a process.

    Called on startup (a restart is exactly when stranded jobs exist) and
    periodically by the worker loop.
    """
    now = datetime.now(timezone.utc)

    # Exhausted attempts first, so a job that keeps killing its worker lands
    # in a terminal state with a reason instead of cycling forever.
    failed = db.query(Document).filter(
        Document.status == STATUS_PROCESSING,
        Document.lease_expires_at.isnot(None),
        Document.lease_expires_at < now,
        Document.attempt_count >= max_attempts,
    ).update(
        {
            "status": STATUS_FAILED,
            "lease_expires_at": None,
            "error_reason": (
                "Ingestion did not complete after repeated attempts. "
                "The server may have restarted during processing. Re-upload to try again."
            ),
        },
        synchronize_session=False,
    )

    requeued = db.query(Document).filter(
        Document.status == STATUS_PROCESSING,
        Document.lease_expires_at.isnot(None),
        Document.lease_expires_at < now,
    ).update(
        {"status": STATUS_PENDING, "lease_expires_at": None},
        synchronize_session=False,
    )

    db.commit()
    return requeued, failed


def mark_ready(db: Session, document_id: int, chunk_count: int) -> None:
    """Terminal success. Does NOT commit: ingestion commits this together
    with the document's chunks so a document can never be readable before its
    chunks exist."""
    db.query(Document).filter(Document.id == document_id).update(
        {
            "status": "ready",
            "chunk_count": chunk_count,
            "lease_expires_at": None,
            "error_reason": None,
        },
        synchronize_session=False,
    )


def mark_failed(db: Session, document_id: int, error_reason: str) -> None:
    """Terminal failure, with a reason the uploader can act on."""
    db.query(Document).filter(Document.id == document_id).update(
        {"status": STATUS_FAILED, "lease_expires_at": None, "error_reason": error_reason[:500]},
        synchronize_session=False,
    )
    db.commit()


def release_for_retry(db: Session, document_id: int, error_reason: str) -> None:
    """Non-terminal failure: hand the job back to the queue so another
    attempt can pick it up, keeping the reason the last attempt failed.

    Used for failures that are plausibly transient (an embedding provider
    timing out, a rate limit). The attempt_count already incremented at claim
    time, so this cannot retry unboundedly.
    """
    db.query(Document).filter(Document.id == document_id).update(
        {"status": STATUS_PENDING, "lease_expires_at": None, "error_reason": error_reason[:500]},
        synchronize_session=False,
    )
    db.commit()

def update_status(
        db: Session, document_id: int, status: str, chunk_count: int | None = None
) -> None:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        return
    document.status = status
    if chunk_count is not None:
        document.chunk_count = chunk_count
    
def get_by_id_for_tenant(db: Session, document_id: int, tenant_id: int) -> Document | None:
    return db.query(Document).filter(
        Document.id == document_id,
        Document.tenant_id == tenant_id,
    ).first()

def delete_by_tenant(db: Session, tenant_id: int) -> None:
    db.query(Document).filter(Document.tenant_id == tenant_id).delete()

def delete_for_tenant(db: Session, document_id: int, tenant_id: int) -> bool:
    """Deletes only the document row. Returns False without deleting
    anything if it doesn't exist or belongs to another tenant, so
    callers can 404 correctly. Caller must delete the document's chunks
    first (chunks.document_id has no ON DELETE CASCADE at the DB level)
    and commit both in one transaction."""
    document = get_by_id_for_tenant(db, document_id, tenant_id)
    if document is None:
        return False
    db.delete(document)
    return True

def list_by_tenant(db: Session, tenant_id: int) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.tenant_id == tenant_id)
        .order_by(Document.upload_time.desc())
        .all()
    )