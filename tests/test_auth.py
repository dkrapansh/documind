def test_issue_key_returns_raw_key_and_tenant_id(client):
    response = client.post("/auth/keys", json={"tenant_name": "acme"})

    assert response.status_code == 200
    body = response.json()
    assert body["api_key"].startswith("dm_")
    body["tenant_id"] == 1 # first tenant in a freshly wiped table

def test_missing_api_key_returns_401(client):
    response = client.get("/foo")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key"

def test_valid_key_passes_auth_returns_404_for_unknown_route(client):
    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    raw_key = issue_response.json()["api_key"]

    response = client.get("/foo", headers={"X-API-Key": raw_key})
    # 404, not 401: proves auth middleware let the request through and
    # FastAPI's router - not our auth later - is what couldn't find /foo.
    assert response.status_code == 404

def test_correlation_id_header_present_on_every_response(client):
    response = client.get("/health")

    assert "x-correlation-id" in response.headers

def test_rate_limit_returns_429_after_limit_exceeded(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.rate_limit_requests", 3)

    issue_response = client.post("/auth/keys", json={"tenant_name": "acme"})
    raw_key = issue_response.json()["api_key"]
    headers = {"X-API-Key": raw_key}

    statuses = [client.get("/foo", headers=headers).status_code for _ in range(5)]

    assert statuses == [404, 404, 404, 429, 429]