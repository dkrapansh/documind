import io

from app.models.tenant import Tenant

def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536

def _seed_demo_tenant(client, monkeypatch) -> None:
    """Recreates the same real-world setup: a non-ephemeral tenant named
    'demo' (settings.seed_tenant_name) with one ready document."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    seed_headers = {
        "X-API-Key": client.post("/auth/keys", json={"tenant_name": "demo"}).json()["api_key"]
    }
    client.post(
        "/documents",
        headers=seed_headers,
        files={"file": ("handbook.txt", io.BytesIO(b"vacation policy content"), "text/plain")},
    )

def test_demo_session_issues_a_working_key_for_a_fresh_isolated_tenant(client, monkeypatch):
    response = client.post("/auth/demo-session")
    assert response.status_code == 200
    body = response.json()
    assert body["api_key"].startswith("dm_")

    headers = {"X-API-Key": body["api_key"]}
    assert client.get("/documents", headers=headers).status_code == 200

def test_demo_session_tenant_is_marked_ephemeral(client, db_session):
    response = client.post("/auth/demo-session")
    tenant_id = response.json()["tenant_id"]

    tenant = db_session.get(Tenant, tenant_id)
    assert tenant.is_ephemeral is True

def test_demo_session_clones_the_seed_corpus_with_no_reembedding(client, monkeypatch):
    _seed_demo_tenant(client, monkeypatch)

    calls = []
    def _tracking_embed(text):
        calls.append(text)
        return [0.1] * 1536
    monkeypatch.setattr("app.clients.embeddings.embed_text", _tracking_embed)

    session_response = client.post("/auth/demo-session")
    headers = {"X-API-Key": session_response.json()["api_key"]}

    docs = client.get("/documents", headers=headers).json()
    assert len(docs) == 1
    assert docs[0]["status"] == "ready"
    assert docs[0]["chunk_count"] == 1
    # cloning copies existing embeddings; it must not call the embedding
    # client at all
    assert calls == []

def test_demo_session_tenants_are_isolated_from_each_other(client, monkeypatch):
    _seed_demo_tenant(client, monkeypatch)

    visitor_a = client.post("/auth/demo-session").json()["api_key"]
    visitor_b = client.post("/auth/demo-session").json()["api_key"]

    client.post(
        "/documents",
        headers={"X-API-Key": visitor_a},
        files={"file": ("a-private.txt", io.BytesIO(b"visitor a's private doc"), "text/plain")},
    )

    a_docs = client.get("/documents", headers={"X-API-Key": visitor_a}).json()
    b_docs = client.get("/documents", headers={"X-API-Key": visitor_b}).json()

    assert any(d["filename"] == "a-private.txt" for d in a_docs)
    assert not any(d["filename"] == "a-private.txt" for d in b_docs)

def test_demo_session_rate_limited_by_ip(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.demo_session_rate_limit", 2)

    statuses = [client.post("/auth/demo-session").status_code for _ in range(4)]

    assert statuses == [200, 200, 429, 429]

def test_sweep_deletes_expired_ephemeral_tenants_on_next_session_creation(
    client, db_session, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    from app.repositories.api_keys import get_by_hashed_key
    from app.core.security import hash_key

    monkeypatch.setattr("app.config.settings.ephemeral_tenant_ttl_minutes", 60)

    old_session = client.post("/auth/demo-session").json()
    old_key_raw = old_session["api_key"]

    # backdate it past the TTL, as if it had been minted an hour ago
    tenant = db_session.get(Tenant, old_session["tenant_id"])
    tenant.created_at = datetime.now(timezone.utc) - timedelta(minutes=61)
    db_session.commit()

    client.post("/auth/demo-session")  # sweep runs lazily on the next mint

    assert db_session.get(Tenant, old_session["tenant_id"]) is None
    assert get_by_hashed_key(db_session, hash_key(old_key_raw)) is None

def test_sweep_leaves_non_ephemeral_tenants_alone(client, db_session, monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr("app.config.settings.ephemeral_tenant_ttl_minutes", 60)

    real_tenant_id = client.post("/auth/keys", json={"tenant_name": "acme"}).json()["tenant_id"]
    tenant = db_session.get(Tenant, real_tenant_id)
    tenant.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db_session.commit()

    client.post("/auth/demo-session")

    db_session.expire_all()
    assert db_session.get(Tenant, real_tenant_id) is not None
