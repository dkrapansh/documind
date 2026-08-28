import logging
import threading

from app.config import settings
from app.db.session import SessionLocal
from app.repositories.documents import claim_next_pending, recover_stale_jobs
from app.services.ingestion import process_document

logger = logging.getLogger(__name__)

# Set by the upload path so a freshly enqueued document starts ingesting
# immediately instead of waiting out the poll interval. The poll interval is
# still the safety net: if this signal is ever missed, or the job was enqueued
# by a different process, the work is still picked up within one interval.
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


def notify_new_job() -> None:
    _wake.set()


def process_available_jobs(max_jobs: int = 100) -> int:
    """Claim and run pending ingestion jobs until none remain. Returns how
    many were processed.

    Separated from the thread loop so tests can drive ingestion
    deterministically, and so a single pass can be triggered on demand,
    without needing a background thread running.

    max_jobs bounds one pass so a large backlog cannot starve the recovery
    sweep or block shutdown indefinitely.
    """
    processed = 0
    db = SessionLocal()
    try:
        while processed < max_jobs:
            document_id = claim_next_pending(
                db,
                lease_seconds=settings.ingestion_lease_seconds,
                max_attempts=settings.ingestion_max_attempts,
            )
            if document_id is None:
                break
            process_document(document_id)
            processed += 1
    finally:
        db.close()
    return processed


def recover_stale() -> tuple[int, int]:
    """Requeue jobs whose worker died holding them. Returns (requeued, failed)."""
    db = SessionLocal()
    try:
        requeued, failed = recover_stale_jobs(db, max_attempts=settings.ingestion_max_attempts)
        if requeued or failed:
            logger.info(
                "recovered stale ingestion jobs",
                extra={"requeued": requeued, "failed": failed},
            )
        return requeued, failed
    finally:
        db.close()


def _run() -> None:
    """Worker loop. Recovers stranded jobs, drains the queue, then waits for
    either a new-job signal or the poll interval, whichever comes first."""
    while not _stop.is_set():
        try:
            recover_stale()
            process_available_jobs()
        except Exception:
            # The loop must outlive any single failure. A worker thread that
            # dies takes ingestion down silently for the life of the process,
            # which is the exact class of failure this whole change exists to
            # remove.
            logger.exception("ingestion worker iteration failed")

        _wake.wait(timeout=settings.ingestion_poll_seconds)
        _wake.clear()


def start_worker() -> None:
    """Start the background ingestion worker.

    A daemon thread inside the API process rather than a separate service:
    the durability guarantee comes from the job state living in Postgres with
    a lease, not from where the worker runs. A second process would add
    deployment cost and another thing to monitor without changing the
    recovery story, since a crashed worker is recovered by lease expiry
    either way. If ingestion volume ever justifies isolating it from request
    traffic, this same loop runs unchanged in its own process.
    """
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    _stop.clear()
    _thread = threading.Thread(target=_run, name="ingestion-worker", daemon=True)
    _thread.start()
    logger.info(
        "ingestion worker started",
        extra={
            "poll_seconds": settings.ingestion_poll_seconds,
            "lease_seconds": settings.ingestion_lease_seconds,
            "max_attempts": settings.ingestion_max_attempts,
        },
    )


def stop_worker(timeout: float = 5.0) -> None:
    """Ask the worker to finish its current job and exit.

    A job still in flight when the timeout expires is not lost: its lease
    expires and another worker (or this process after restart) reclaims it.
    That is the point of leasing rather than locking.
    """
    global _thread
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
        _thread = None
