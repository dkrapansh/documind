import json

from app import APP_VERSION


def test_health_live_reports_version_without_auth(client):
    """Liveness must answer with no API key: it is what the platform health
    check calls, and a 401 there would look like a dead instance."""
    response = client.get("/health/live")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert body["version"] == APP_VERSION
    assert "git_sha" in body


def test_legacy_health_path_still_works(client):
    """The old /health path stays an alias so an existing platform health
    check does not start failing the moment this deploys."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_health_live_does_not_touch_the_database(client, monkeypatch):
    """The whole point of splitting live from ready. If liveness queried the
    database, a database outage would fail the platform health check, and
    every replacement instance would be killed before anyone could read its
    logs. This asserts liveness survives a database that raises on contact."""
    def _boom():
        raise RuntimeError("database is gone")

    monkeypatch.setattr("app.services.health.check_connection", _boom)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_health_ready_reports_each_dependency(client):
    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"]["database"]["status"] == "ok"
    assert body["dependencies"]["embedding_provider"]["status"] == "configured"
    assert body["dependencies"]["generation_provider"]["status"] == "configured"
    # Lazy by design, so a freshly booted instance reporting "not_loaded"
    # is normal and must not make the instance unready.
    assert body["dependencies"]["reranker"]["status"] in ("loaded", "not_loaded")


def test_health_ready_confirms_schema_matches_the_code(client):
    """The check that makes scripts/start.sh safe: migrations no longer gate
    the server, so readiness is what catches an instance booted against a
    schema its code does not expect. The test suite builds the schema with a
    real `alembic upgrade head`, so this must report the head revision."""
    body = client.get("/health/ready").json()

    migrations = body["dependencies"]["migrations"]
    assert migrations["status"] == "ok"
    assert migrations["revision"]


def test_health_ready_returns_503_when_the_database_is_unreachable(client, monkeypatch):
    def _boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.services.health.check_connection", _boom)

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["database"]["status"] == "error"
    assert body["dependencies"]["database"]["error_type"] == "RuntimeError"


def test_health_ready_reports_error_type_but_not_the_message(client, monkeypatch):
    """A connection error's message routinely carries the host, the user, and
    sometimes the password from a connection URL. This endpoint is
    unauthenticated, so it reports the exception type and nothing else."""
    def _boom():
        raise RuntimeError("could not connect to host=db.internal user=admin password=hunter2")

    monkeypatch.setattr("app.services.health.check_connection", _boom)

    body = client.get("/health/ready").text

    assert "hunter2" not in body
    assert "db.internal" not in body


def test_health_ready_never_exposes_secrets(client):
    """Blanket check against a future field being added carelessly: no part
    of the readiness payload may contain a credential or a connection URL."""
    from app.config import settings

    body = json.dumps(client.get("/health/ready").json())

    assert settings.gemini_api_key not in body
    assert settings.database_url not in body
    assert "password" not in body.lower()
