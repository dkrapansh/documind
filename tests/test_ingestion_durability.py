"""Tests for the durable ingestion job: leasing, recovery, retry safety.

These cover the failure that motivated the whole change. Ingestion used to
live in a FastAPI BackgroundTask, so a restart mid-job left a document at
"processing" forever with nothing recording that work had started. The tests
below drive the real claim/lease/recover machinery against a real Postgres,
because the guarantees being tested (atomic claim, lease expiry, uniqueness)
are database behavior, not Python behavior, and would pass trivially against
a mock.
"""
import io
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_content import DocumentContent
from app.repositories.documents import claim_next_pending, recover_stale_jobs
from app.services.ingestion import process_document
from app.services.ingestion_worker import process_available_jobs as drain_ingestion


def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536


def _auth_headers(client, tenant_name="acme") -> dict:
    response = client.post("/auth/keys", json={"tenant_name": tenant_name})
    return {"X-API-Key": response.json()["api_key"]}


def _upload(client, headers, name="durability.txt", body=b"Durable ingestion test document."):
    return client.post(
        "/documents",
        headers=headers,
        files={"file": (name, io.BytesIO(body), "text/plain")},
    )


# --- Leasing and recovery -------------------------------------------------

def test_claim_marks_the_job_processing_and_takes_a_lease(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]

    claimed_id = claim_next_pending(db_session, lease_seconds=600, max_attempts=3)
    assert claimed_id == document_id

    document = db_session.query(Document).filter(Document.id == document_id).one()
    assert document.status == "processing"
    # Incremented at claim time, not completion, so a worker that dies
    # without reporting back still burns an attempt.
    assert document.attempt_count == 1
    assert document.processing_started_at is not None
    assert document.lease_expires_at is not None


def test_claim_returns_none_when_nothing_is_pending(client, db_session):
    assert claim_next_pending(db_session, lease_seconds=600, max_attempts=3) is None


def test_two_workers_never_claim_the_same_job(client, db_session, test_engine, monkeypatch):
    """The whole point of FOR UPDATE SKIP LOCKED. Two concurrent claims must
    take two different jobs, never the same one twice."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    first_id = _upload(client, headers, "one.txt", b"First document.").json()["id"]
    second_id = _upload(client, headers, "two.txt", b"Second document.").json()["id"]

    Session = sessionmaker(bind=test_engine)
    worker_a, worker_b = Session(), Session()
    try:
        claimed_a = claim_next_pending(worker_a, lease_seconds=600, max_attempts=3)
        claimed_b = claim_next_pending(worker_b, lease_seconds=600, max_attempts=3)
    finally:
        worker_a.close()
        worker_b.close()

    assert claimed_a is not None and claimed_b is not None
    assert claimed_a != claimed_b
    assert {claimed_a, claimed_b} == {first_id, second_id}


def test_expired_lease_returns_a_stranded_job_to_the_queue(client, db_session, monkeypatch):
    """The restart-safety guarantee: a job whose worker died is claimable
    again once its lease expires, with no coordinator involved."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]

    claim_next_pending(db_session, lease_seconds=600, max_attempts=3)

    # Simulate the worker dying: the lease is now in the past.
    db_session.query(Document).filter(Document.id == document_id).update(
        {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )
    db_session.commit()

    requeued, failed = recover_stale_jobs(db_session, max_attempts=3)
    assert (requeued, failed) == (1, 0)

    db_session.expire_all()
    assert db_session.query(Document).filter(Document.id == document_id).one().status == "pending"
    # And it is genuinely claimable again, not just relabelled.
    assert claim_next_pending(db_session, lease_seconds=600, max_attempts=3) == document_id


def test_a_live_lease_is_left_alone_by_recovery(client, db_session, monkeypatch):
    """Recovery must not steal a job from a worker that is still working."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]
    claim_next_pending(db_session, lease_seconds=600, max_attempts=3)

    requeued, failed = recover_stale_jobs(db_session, max_attempts=3)
    assert (requeued, failed) == (0, 0)

    db_session.expire_all()
    assert db_session.query(Document).filter(Document.id == document_id).one().status == "processing"


def test_job_that_exhausts_its_attempts_fails_with_a_reason(client, db_session, monkeypatch):
    """A job that reliably kills its worker must stop, not cycle forever."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]

    db_session.query(Document).filter(Document.id == document_id).update(
        {
            "status": "processing",
            "attempt_count": 3,
            "lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
    )
    db_session.commit()

    requeued, failed = recover_stale_jobs(db_session, max_attempts=3)
    assert failed == 1

    db_session.expire_all()
    document = db_session.query(Document).filter(Document.id == document_id).one()
    assert document.status == "failed"
    assert document.error_reason is not None
    assert "re-upload" in document.error_reason.lower()


def test_claim_skips_jobs_that_are_out_of_attempts(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]
    db_session.query(Document).filter(Document.id == document_id).update({"attempt_count": 3})
    db_session.commit()

    assert claim_next_pending(db_session, lease_seconds=600, max_attempts=3) is None


# --- Retry safety ---------------------------------------------------------

def test_reingesting_replaces_chunks_instead_of_duplicating_them(client, db_session, monkeypatch):
    """Idempotency. A retry must not leave two copies of every chunk, which
    would distort BM25 term statistics and let the same text occupy several
    slots in the final reranked context."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]
    drain_ingestion()

    first_count = db_session.query(Chunk).filter(Chunk.document_id == document_id).count()
    assert first_count > 0

    # Run the same job again, exactly as a retry after a crash would.
    process_document(document_id)

    db_session.expire_all()
    assert db_session.query(Chunk).filter(Chunk.document_id == document_id).count() == first_count
    assert db_session.query(Document).filter(Document.id == document_id).one().status == "ready"


def test_database_rejects_a_duplicate_chunk_index(client, db_session, monkeypatch):
    """The backstop behind the delete-then-insert above. If ingestion ever
    stopped clearing old chunks, this constraint turns a silent corruption
    into a loud failure."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]
    drain_ingestion()

    document = db_session.query(Document).filter(Document.id == document_id).one()
    existing = db_session.query(Chunk).filter(Chunk.document_id == document_id).first()

    db_session.add(
        Chunk(
            document_id=document_id,
            tenant_id=document.tenant_id,
            chunk_index=existing.chunk_index,
            text="a duplicate of an index that already exists",
            embedding=[0.1] * 1536,
            token_count=5,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- Upload-time validation ----------------------------------------------

def test_document_with_no_extractable_text_is_rejected_at_upload(client):
    """Extraction moved into the request, so an unreadable file fails
    immediately with a reason instead of returning 200 and landing in
    "failed" minutes later with nothing recorded."""
    headers = _auth_headers(client)
    response = _upload(client, headers, "empty.txt", b"   \n\t  \n  ")

    assert response.status_code == 422
    assert "no readable text" in response.json()["detail"].lower()
    # And nothing was enqueued.
    assert drain_ingestion() == 0


def test_failed_document_can_be_retried_by_reuploading(client, db_session, monkeypatch):
    """get_by_content_hash used to match failed rows, so re-uploading a file
    that failed returned the failed document with HTTP 200 and no new job:
    the upload looked successful but could never become ready."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    body = b"A document that will be marked failed."
    first_id = _upload(client, headers, "retry.txt", body).json()["id"]
    drain_ingestion()

    db_session.query(Document).filter(Document.id == first_id).update(
        {"status": "failed", "error_reason": "simulated earlier failure"}
    )
    db_session.commit()

    second = _upload(client, headers, "retry.txt", body)
    assert second.status_code == 200
    assert second.json()["id"] != first_id, "re-upload must create a new job, not return the failed one"

    assert drain_ingestion() == 1
    db_session.expire_all()
    assert db_session.query(Document).filter(Document.id == second.json()["id"]).one().status == "ready"


def test_upload_without_a_filename_is_not_a_500(client):
    """Path(None) used to raise TypeError and escape as an unhandled 500."""
    headers = _auth_headers(client)
    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("", io.BytesIO(b"content"), "text/plain")},
    )
    assert response.status_code != 500
    assert response.status_code in (400, 422)


def test_document_over_the_chunk_cap_fails_without_embedding_anything(client, db_session, monkeypatch):
    """Bounds embedding spend. The 20MB upload cap limits bytes, not work:
    without this one upload could consume a whole day of free-tier quota."""
    calls = []

    def _counting_embed(text: str) -> list[float]:
        calls.append(text)
        return [0.1] * 1536

    monkeypatch.setattr("app.services.ingestion.embed_text", _counting_embed)
    monkeypatch.setattr(settings, "max_chunks_per_document", 2)

    headers = _auth_headers(client)
    body = ("word " * 4000).encode("utf-8")
    document_id = _upload(client, headers, "huge.txt", body).json()["id"]
    drain_ingestion()

    db_session.expire_all()
    document = db_session.query(Document).filter(Document.id == document_id).one()
    assert document.status == "failed"
    assert "limit" in document.error_reason.lower()
    assert calls == [], "no embedding should be paid for once the cap is known to be exceeded"


def test_error_reason_is_visible_on_the_document_response(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]
    drain_ingestion()

    db_session.query(Document).filter(Document.id == document_id).update(
        {"status": "failed", "error_reason": "a reason the uploader can act on"}
    )
    db_session.commit()

    body = client.get(f"/documents/{document_id}", headers=headers).json()
    assert body["status"] == "failed"
    assert body["error_reason"] == "a reason the uploader can act on"


# --- Durability of the stored text ---------------------------------------

def test_extracted_text_is_stored_in_postgres_not_on_disk(client, db_session):
    """The restart-safety guarantee for the job's input. Raw uploads used to
    go to the container's local disk, which is ephemeral on the deployment
    target, so a restart between upload and ingestion destroyed the input and
    no retry could ever fix it."""
    headers = _auth_headers(client)
    body = b"This exact text must survive a restart."
    document_id = _upload(client, headers, "durable.txt", body).json()["id"]

    content = db_session.query(DocumentContent).filter(
        DocumentContent.document_id == document_id
    ).one()
    assert body.decode("utf-8") in content.text


def test_deleting_a_document_also_deletes_its_stored_text(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)
    document_id = _upload(client, headers).json()["id"]
    drain_ingestion()

    assert client.delete(f"/documents/{document_id}", headers=headers).status_code in (200, 204)

    db_session.expire_all()
    assert db_session.query(DocumentContent).filter(
        DocumentContent.document_id == document_id
    ).count() == 0
