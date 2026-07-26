import io

def _auth_headers(client, tenant_name: str = "acme") -> dict:
    response = client.post("/auth/keys", json={"tenant_name": tenant_name})
    raw_key = response.json()["api_key"]
    return {"X-API-Key": raw_key}

def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536

def test_list_documents_is_scoped_to_the_requesting_tenant(client, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)

    owner_headers = _auth_headers(client, "acme")
    other_headers = _auth_headers(client, "globex")

    client.post(
        "/documents",
        headers=owner_headers,
        files={"file": ("owner.txt", io.BytesIO(b"owner content"), "text/plain")},
    )

    owner_list = client.get("/documents", headers=owner_headers)
    other_list = client.get("/documents", headers=other_headers)

    assert len(owner_list.json()) == 1
    assert other_list.json() == []

def test_get_document_status_404s_for_a_different_tenant(client, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)

    owner_headers = _auth_headers(client, "acme")
    other_headers = _auth_headers(client, "globex")

    upload_response = client.post(
        "/documents",
        headers=owner_headers,
        files={"file": ("owner.txt", io.BytesIO(b"owner content"), "text/plain")},
    )
    document_id = upload_response.json()["id"]

    owner_response = client.get(f"/documents/{document_id}", headers=owner_headers)
    other_response = client.get(f"/documents/{document_id}", headers=other_headers)

    assert owner_response.status_code == 200
    assert other_response.status_code == 404
    assert other_response.json()["detail"] == "Document not found"

def test_upload_rejects_unsupported_file_extension(client):
    headers = _auth_headers(client)

    response = client.post(
        "/documents",
        headers=headers,
        files={
            "file": ("malware.exe", io.BytesIO(b"binary junk"), "application/octet-stream")
        },
    )

    assert response.status_code == 400
    assert "Unsupported file type" in response.json()["detail"]

def test_delete_document_removes_it_and_its_chunks(client, db_session, monkeypatch):
    from app.models.chunk import Chunk

    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    headers = _auth_headers(client)

    upload_response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("owner.txt", io.BytesIO(b"owner content"), "text/plain")},
    )
    document_id = upload_response.json()["id"]
    assert db_session.query(Chunk).filter(Chunk.document_id == document_id).count() > 0

    delete_response = client.delete(f"/documents/{document_id}", headers=headers)
    assert delete_response.status_code == 204

    get_response = client.get(f"/documents/{document_id}", headers=headers)
    assert get_response.status_code == 404
    db_session.expire_all()
    assert db_session.query(Chunk).filter(Chunk.document_id == document_id).count() == 0

def test_delete_document_404s_for_a_different_tenant(client, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    owner_headers = _auth_headers(client, "acme")
    other_headers = _auth_headers(client, "globex")

    upload_response = client.post(
        "/documents",
        headers=owner_headers,
        files={"file": ("owner.txt", io.BytesIO(b"owner content"), "text/plain")},
    )
    document_id = upload_response.json()["id"]

    response = client.delete(f"/documents/{document_id}", headers=other_headers)
    assert response.status_code == 404

    still_there = client.get(f"/documents/{document_id}", headers=owner_headers)
    assert still_there.status_code == 200

def test_delete_unknown_document_returns_404(client):
    headers = _auth_headers(client)
    response = client.delete("/documents/999999", headers=headers)
    assert response.status_code == 404
