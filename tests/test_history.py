import io

def _auth_headers(client, tenant_name: str = "acme") -> dict:
    response = client.post("/auth/keys", json={"tenant_name": tenant_name})
    raw_key = response.json()["api_key"]
    return {"X-API-Key": raw_key}

def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536

def _upload_and_wait_ready(client, headers) -> int:
    file_content = b"Refund Policy: Refunds are available within 30 days of purchase."
    upload_response = client.post(
        "/documents",
        headers=headers,
        files={"file": ("policy.txt", io.BytesIO(file_content), "text/plain")},
    )
    document_id = upload_response.json()["id"]
    client.get(f"/documents/{document_id}", headers=headers)
    return document_id

def test_second_query_reuses_session_id_and_history_returns_both_in_order(client, monkeypatch):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)
    monkeypatch.setattr(
        "app.services.answering.generate_answer",
        lambda messages: "Refunds are available within 30 days of purchase.",
    )

    headers = _auth_headers(client)
    _upload_and_wait_ready(client, headers)

    first = client.post("/query", headers=headers, json={"question": "What is the refund policy?"})
    session_id = first.json()["session_id"]
    assert session_id

    second = client.post(
        "/query",
        headers=headers,
        json={"question": "How many days do I have?", "session_id": session_id},
    )
    assert second.json()["session_id"] == session_id

    history_response = client.get(f"/history/{session_id}", headers=headers)
    assert history_response.status_code == 200
    entries = history_response.json()
    assert [entry["question"] for entry in entries] == [
        "What is the refund policy?",
        "How many days do I have?",
    ]

def test_history_is_scoped_to_the_requesting_tenant(client, monkeypatch):
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)

    owner_headers = _auth_headers(client, "acme")
    other_headers = _auth_headers(client, "globex")

    query_response = client.post(
        "/query", headers=owner_headers, json={"question": "What is the refund policy?"}
    )
    session_id = query_response.json()["session_id"]

    owner_history = client.get(f"/history/{session_id}", headers=owner_headers)
    other_history = client.get(f"/history/{session_id}", headers=other_headers)

    assert len(owner_history.json()) == 1
    assert other_history.json() == []
