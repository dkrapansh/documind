import io

from app.models.query_log import QueryLog
from app.services.ingestion_worker import process_available_jobs as drain_ingestion

def _auth_headers(client) -> dict:
    response = client.post("/auth/keys", json={"tenant_name": "acme"})
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
    drain_ingestion()
    document_id = upload_response.json()["id"]
    client.get(f"/documents/{document_id}", headers=headers)
    return document_id

def _parse_sse(body: str) -> list[tuple[str, str]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(l.split(": ", 1)[1] for l in lines if l.startswith("event: "))
        data = next(l.split(": ", 1)[1] for l in lines if l.startswith("data: "))
        events.append((event, data))
    return events

def test_stream_yields_sources_then_deltas_then_done_and_logs_full_answer(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)
    monkeypatch.setattr(
        "app.services.answering.stream_answer",
        lambda messages: iter(["Refunds ", "are available ", "within 30 days."]),
    )

    headers = _auth_headers(client)
    document_id = _upload_and_wait_ready(client, headers)

    response = client.get(
        "/query/stream",
        headers=headers,
        params={"question": "What is the refund policy?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]
    assert event_names == ["sources", "session", "delta", "delta", "delta", "done"]

    import json
    sources = json.loads(events[0][1])
    assert sources[0]["document_id"] == document_id

    deltas = [json.loads(data)["text"] for name, data in events if name == "delta"]
    assert deltas == ["Refunds ", "are available ", "within 30 days."]

    [log] = db_session.query(QueryLog).all()
    assert log.answer == "Refunds are available within 30 days."
    assert log.confidence is not None

def test_stream_generation_failure_emits_error_event_and_is_not_cached(
    client, db_session, monkeypatch
):
    """A failure partway through streaming must not look like a
    successful, truncated answer: the client needs an explicit signal
    (an `error` event), the logged answer must be the failure message
    not a partial one, and the failure must not get cached (a transient
    Gemini failure shouldn't poison the next identical question)."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)

    call_count = {"n": 0}

    def _failing_stream(messages):
        call_count["n"] += 1
        yield "Refunds "
        raise RuntimeError("simulated mid-stream failure")

    monkeypatch.setattr("app.services.answering.stream_answer", _failing_stream)

    headers = _auth_headers(client)
    _upload_and_wait_ready(client, headers)

    response = client.get(
        "/query/stream",
        headers=headers,
        params={"question": "What is the refund policy?"},
    )
    assert response.status_code == 200

    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]
    assert event_names == ["sources", "session", "delta", "error", "done"]

    import json
    error_payload = json.loads(next(d for n, d in events if n == "error"))
    assert "went wrong" in error_payload["message"]

    [log] = db_session.query(QueryLog).all()
    assert log.answer == error_payload["message"]

    # A second identical question must not replay a cached failure -
    # it should hit generation again, not the cache.
    client.get(
        "/query/stream",
        headers=headers,
        params={"question": "What is the refund policy?"},
    )
    assert call_count["n"] == 2

def test_stream_second_identical_call_hits_cache_and_skips_generation(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)

    call_count = {"n": 0}

    def _tracking_stream(messages):
        call_count["n"] += 1
        yield "Refunds are available within 30 days."

    monkeypatch.setattr("app.services.answering.stream_answer", _tracking_stream)

    headers = _auth_headers(client)
    _upload_and_wait_ready(client, headers)

    first = client.get(
        "/query/stream",
        headers=headers,
        params={"question": "What is the refund policy?"},
    )
    assert [n for n, _ in _parse_sse(first.text)] == ["sources", "session", "delta", "done"]
    assert call_count["n"] == 1

    second = client.get(
        "/query/stream",
        headers=headers,
        params={"question": "What is the refund policy?"},
    )
    second_events = _parse_sse(second.text)
    assert [n for n, _ in second_events] == ["sources", "session", "delta", "done"]
    assert call_count["n"] == 1  # cache hit - generation never called again

    import json
    deltas = [json.loads(d)["text"] for n, d in second_events if n == "delta"]
    assert deltas == ["Refunds are available within 30 days."]

    logs = db_session.query(QueryLog).order_by(QueryLog.id).all()
    assert len(logs) == 2
    assert logs[1].answer == "Refunds are available within 30 days."

def test_stream_refusal_when_no_chunks_match(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)
    headers = _auth_headers(client)

    response = client.get(
        "/query/stream",
        headers=headers,
        params={"question": "What is the refund policy?"},
    )
    events = _parse_sse(response.text)

    import json
    sources = json.loads(events[0][1])
    assert sources == []

    [(_, delta_data)] = [(n, d) for n, d in events if n == "delta"]
    assert "don't have enough relevant information" in json.loads(delta_data)["text"]

    [log] = db_session.query(QueryLog).all()
    assert log.confidence is None
