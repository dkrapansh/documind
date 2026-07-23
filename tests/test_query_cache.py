import time

import app.services.query_cache as query_cache
from app.services.query_cache import (
    bump_scope,
    get_cached_answer,
    normalize_question,
    set_cached_answer,
)


def _reset_cache(monkeypatch):
    """Module-level state (see query_cache.py's _entries/_scope_versions) is
    process-wide, so tests reach in and reset it directly rather than
    relying on tenant_id never repeating across tests."""
    monkeypatch.setattr(query_cache, "_entries", {})
    monkeypatch.setattr(query_cache, "_scope_versions", {})


def test_normalize_question_collapses_case_and_whitespace():
    assert normalize_question("  What IS   Foo?  ") == "what is foo?"


def test_cache_miss_when_never_set(monkeypatch):
    _reset_cache(monkeypatch)
    assert get_cached_answer(1, "What is Foo?") is None


def test_cache_hit_is_keyed_by_normalized_question(monkeypatch):
    _reset_cache(monkeypatch)
    set_cached_answer(1, "What is Foo?", "bar", sources=[], confidence=0.5)

    cached = get_cached_answer(1, "  what IS   foo?  ")
    assert cached is not None
    assert cached.answer == "bar"
    assert cached.confidence == 0.5


def test_cache_is_scoped_per_tenant(monkeypatch):
    _reset_cache(monkeypatch)
    set_cached_answer(1, "What is Foo?", "bar", sources=[], confidence=0.5)

    assert get_cached_answer(2, "What is Foo?") is None


def test_bump_scope_invalidates_only_that_tenants_entries(monkeypatch):
    _reset_cache(monkeypatch)
    set_cached_answer(1, "What is Foo?", "bar", sources=[], confidence=0.5)
    set_cached_answer(2, "What is Foo?", "baz", sources=[], confidence=0.5)

    bump_scope(1)

    assert get_cached_answer(1, "What is Foo?") is None
    assert get_cached_answer(2, "What is Foo?") is not None


def test_entry_expires_after_ttl(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(query_cache.settings, "cache_ttl_seconds", 0)

    set_cached_answer(1, "What is Foo?", "bar", sources=[], confidence=0.5)
    # Comfortably past Windows' default ~15ms timer granularity, so this
    # can't flake on a tight sleep racing the OS scheduler.
    time.sleep(0.05)

    assert get_cached_answer(1, "What is Foo?") is None
