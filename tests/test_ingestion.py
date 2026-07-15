import io

from app.models.chunk import Chunk
from app.models.document import Document

def _fake_embed_text(text: str) -> list[float]:
    """Stand-in for the real OpenAI call — instant, free, deterministic.
    Ingestion only needs *a* vector of the right shape to prove the
    pipeline wires together; it doesn't need a real embedding to test
    chunking, DB writes, or status transitions."""
    return [0.1] * 1536

def _auth_headers(client) -> dict:
    response = client.post("/auth/keys", json={"tenant_name": "acme"})
    raw_key = response.json()["api_key"]
    return {"X-API-Key": raw_key}

def test_upload_ingests_document_into_chunks_with_embeddings(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)

    file_content = b"Hello world. This is a small test document for ingestion."
    response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("ingestion_test.txt", io.BytesIO(file_content), "text/plain")},
    )
    assert response.status_code == 200
    document_id = response.json()["id"]

    status_response = client.get(f"/documents/{document_id}", headers=headers)
    body = status_response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] == 1  # short text stays under one chunk

    chunks = db_session.query(Chunk).filter(Chunk.document_id == document_id).all()
    assert len(chunks) == 1
    assert chunks[0].text.strip() == file_content.decode("utf-8").strip()
    assert len(chunks[0].embedding) == 1536

def test_reupload_same_file_is_a_noop(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)

    file_content = b"Duplicate upload content for idempotency test."

    first = client.post(
        "/documents",
        headers=headers,
        files={"file": ("dup_test.txt", io.BytesIO(file_content), "text/plain")},
    )
    second = client.post(
        "/documents",
        headers=headers,
        files={"file": ("dup_test.txt", io.BytesIO(file_content), "text/plain")},
    )

    assert first.json()["id"] == second.json()["id"]

    documents = db_session.query(Document).all()
    assert len(documents) == 1

    chunks = db_session.query(Chunk).filter(Chunk.document_id == first.json()["id"]).all()
    assert len(chunks) == 1