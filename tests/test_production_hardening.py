"""Tests for the production-hardening pass: error contract, reranker
failure path, eval concurrency, and cache eviction.

Each of these was a way the service could fail badly while telling nobody
useful: a bare 500 with an empty body, a request hanging on a model download,
two evaluation runs exhausting a shared quota, and a cache that only ever
grew.
"""
import io

import pytest

from app.config import settings
from app.core.exceptions import RerankerUnavailableException
from app.services.ingestion_worker import process_available_jobs as drain_ingestion


def _auth_headers(client, tenant_name="acme") -> dict:
    response = client.post("/auth/keys", json={"tenant_name": tenant_name})
    return {"X-API-Key": response.json()["api_key"]}


def _fake_embed_text(text: str) -> list[float]:
    return [0.1] * 1536


# --- Error contract -------------------------------------------------------

def test_expected_errors_carry_a_code_and_correlation_id(client):
    """Clients branch on `code`; matching on `detail` breaks the moment the
    wording is improved. `correlation_id` is what ties the response a user
    saw to this request's log records."""
    response = client.get("/documents/999999", headers=_auth_headers(client))

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "document_not_found"
    assert body["correlation_id"]
    assert body["detail"]


def test_unhandled_exception_returns_the_same_shape_not_a_bare_500(client, monkeypatch):
    """Anything that is not an AppException is a bug. It used to return
    Starlette's default 500: empty body, nothing logged by this application,
    no correlation id, so the only evidence was a platform access log line.

    Needs its own TestClient with raise_server_exceptions=False. The default
    re-raises the exception into the test instead of returning the response
    the handler produced, which is exactly the response a real client gets.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated bug with a secret: postgres://user:pw@host/db")

    monkeypatch.setattr("app.api.routers.documents.list_by_tenant", _boom)

    headers = _auth_headers(client)
    with TestClient(app, raise_server_exceptions=False) as raw_client:
        response = raw_client.get("/documents", headers=headers)

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "internal_error"
    assert body["correlation_id"], "a 500 without a correlation id cannot be traced"
    # The exception text can carry a connection string, user data, or a
    # filesystem path. None of it belongs in a response.
    assert "postgres://" not in response.text
    assert "simulated bug" not in response.text


def test_every_app_exception_declares_a_unique_code():
    """A duplicated code would make two different failures indistinguishable
    to a client that branches on it."""
    import inspect

    from app.core import exceptions as exc_module

    codes = [
        cls.code
        for _, cls in vars(exc_module).items()
        if inspect.isclass(cls) and issubclass(cls, exc_module.AppException)
    ]
    assert len(codes) == len(set(codes)), "duplicate error codes: %s" % sorted(codes)


# --- Reranker failure path ------------------------------------------------

def test_reranker_load_failure_is_a_503_not_a_hang_or_a_500(client, db_session, monkeypatch):
    """The model loads on first use, which can mean a download from a CDN
    this service does not control. That failure used to surface as an
    unhandled 500 with the cause buried in a traceback."""
    monkeypatch.setattr("app.services.ingestion.embed_text", _fake_embed_text)
    monkeypatch.setattr("app.services.retrieval.embed_text", _fake_embed_text)

    headers = _auth_headers(client)
    client.post(
        "/documents",
        headers=headers,
        files={"file": ("d.txt", io.BytesIO(b"Some indexed content."), "text/plain")},
    )
    drain_ingestion()

    def _fail_to_rank(*args, **kwargs):
        raise RerankerUnavailableException()

    monkeypatch.setattr("app.services.reranking.rerank_chunks", _fail_to_rank)

    response = client.post("/query", headers=headers, json={"question": "anything"})

    assert response.status_code == 503
    assert response.json()["code"] == "reranker_unavailable"


def test_reranker_singleton_is_not_poisoned_by_a_failed_load(monkeypatch):
    """A CDN outage is usually transient. Caching the failure would turn it
    into one that lasts until the next deploy."""
    import app.clients.reranker as reranker_module

    monkeypatch.setattr(reranker_module, "_ranker", None)

    attempts = {"n": 0}

    class _Boom:
        def __init__(self, *args, **kwargs):
            attempts["n"] += 1
            raise OSError("simulated download failure")

    monkeypatch.setattr("flashrank.Ranker", _Boom)

    for _ in range(2):
        with pytest.raises(RerankerUnavailableException):
            reranker_module._get_ranker()

    assert attempts["n"] == 2, "a failed load must be retried, not cached"
    assert reranker_module._ranker is None


# --- Eval concurrency -----------------------------------------------------

def test_second_concurrent_eval_run_is_refused(client, monkeypatch):
    """A run is minutes of real model calls against a shared free-tier quota.
    Two at once do not merely cost twice as much: they exhaust the
    per-minute quota so both record null scores."""
    import app.services.evaluation as evaluation

    monkeypatch.setattr(evaluation, "_active_runs", set())
    # Never let the real run start; the guard is what is under test.
    monkeypatch.setattr(
        "app.api.routers.eval.run_eval_in_background", lambda *a, **k: None
    )

    headers = _auth_headers(client, "eval-tenant")

    first = client.post("/eval/runs", headers=headers, json={})
    assert first.status_code == 200

    second = client.post("/eval/runs", headers=headers, json={})
    assert second.status_code == 409
    assert second.json()["code"] == "eval_run_already_active"


def test_the_run_slot_is_released_so_a_tenant_is_not_locked_out(client, monkeypatch):
    """Released by the background task when the run actually finishes. If a
    crashed run left the slot held, the tenant could never run another until
    the next deploy."""
    import app.services.evaluation as evaluation

    monkeypatch.setattr(evaluation, "_active_runs", set())
    assert evaluation._claim_run_slot(42) is True
    assert evaluation._claim_run_slot(42) is False

    evaluation._release_run_slot(42)
    assert evaluation._claim_run_slot(42) is True, "slot was never released"


# --- Cache eviction -------------------------------------------------------

def test_cache_is_bounded_and_evicts_oldest_first(monkeypatch):
    """TTL alone never bounded this. An entry was only removed when someone
    read it after expiry, so a question asked once stayed resident, and
    scope-invalidated entries became unreachable and therefore immortal."""
    import app.services.query_cache as cache

    monkeypatch.setattr(cache, "_entries", {})
    monkeypatch.setattr(cache, "_scope_versions", {})
    monkeypatch.setattr(settings, "cache_max_entries", 5)

    for i in range(20):
        cache.set_cached_answer(1, "question number %d" % i, "answer %d" % i, [], 0.9)

    assert len(cache._entries) <= 5, "cache grew past its ceiling"
    # The most recent writes survive; the oldest were evicted.
    assert cache.get_cached_answer(1, "question number 19") is not None
    assert cache.get_cached_answer(1, "question number 0") is None


def test_eviction_prefers_expired_entries_over_live_ones(monkeypatch):
    import time

    import app.services.query_cache as cache

    monkeypatch.setattr(cache, "_entries", {})
    monkeypatch.setattr(cache, "_scope_versions", {})
    monkeypatch.setattr(settings, "cache_max_entries", 3)
    monkeypatch.setattr(settings, "cache_ttl_seconds", -1)  # already expired

    for i in range(3):
        cache.set_cached_answer(1, "stale %d" % i, "a", [], 0.9)

    monkeypatch.setattr(settings, "cache_ttl_seconds", 300)
    cache.set_cached_answer(1, "fresh", "a", [], 0.9)

    assert cache.get_cached_answer(1, "fresh") is not None, "a live entry was evicted first"
