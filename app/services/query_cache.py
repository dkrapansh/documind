import re
import threading
import time
from dataclasses import dataclass

from app.config import settings
from app.schemas.query import RetrievedChunk

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    """Collapses casing and whitespace differences so "What's the refund
    policy?" and "  what's the refund policy?  " land on the same cache key
    - callers vary on both constantly (copy-paste, mobile autocapitalize)."""
    return _WHITESPACE_RE.sub(" ", question.strip().lower())


@dataclass
class CachedAnswer:
    answer: str
    sources: list[RetrievedChunk]
    confidence: float | None


@dataclass
class _CacheEntry:
    value: CachedAnswer
    expires_at: float


# Module-level state: this is an in-process cache, one copy per running app
# instance, gone on restart - matches the "exact-match, no external cache
# store" decision in CLAUDE.md. A lock guards both dicts because FastAPI runs
# sync route handlers in a threadpool, so concurrent requests can hit these
# at the same time; a plain dict's check-then-set is not atomic.
_lock = threading.Lock()
_entries: dict[tuple[int, str, int], _CacheEntry] = {}
_scope_versions: dict[int, int] = {}


def _make_key(tenant_id: int, question: str) -> tuple[int, str, int]:
    scope_version = _scope_versions.get(tenant_id, 0)
    return (tenant_id, normalize_question(question), scope_version)


def get_cached_answer(tenant_id: int, question: str) -> CachedAnswer | None:
    """Cache-aside read. Returns None on any kind of miss - never cached,
    expired past cache_ttl_seconds, or the tenant's document set changed
    since this was cached (see bump_scope) - and the caller falls through to
    the real retrieval + answering pipeline exactly as if there were no
    cache at all."""
    key = _make_key(tenant_id, question)
    with _lock:
        entry = _entries.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            del _entries[key]
            return None
        return entry.value


def set_cached_answer(
    tenant_id: int,
    question: str,
    answer: str,
    sources: list[RetrievedChunk],
    confidence: float | None,
) -> None:
    """Caches by (tenant, normalized question, current scope version) only -
    deliberately not the caller's session_id, which is per-request and would
    leak from whichever request happened to populate the cache into every
    later cache hit."""
    key = _make_key(tenant_id, question)
    entry = _CacheEntry(
        value=CachedAnswer(answer=answer, sources=sources, confidence=confidence),
        expires_at=time.monotonic() + settings.cache_ttl_seconds,
    )
    with _lock:
        _entries[key] = entry


def bump_scope(tenant_id: int) -> None:
    """Invalidates every cached answer for this tenant in O(1) by advancing
    its document-scope version, rather than scanning the cache for matching
    entries to delete. Existing entries were keyed with the old version, so
    they simply become unreachable and age out later via TTL.

    Call this whenever the tenant's ready-document set changes (a document
    finishes ingesting, successfully or not) - previously cached answers may
    now be missing information a new document would have supplied, or a
    previous refusal may now be answerable.
    """
    with _lock:
        _scope_versions[tenant_id] = _scope_versions.get(tenant_id, 0) + 1
