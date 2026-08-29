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


# In-process cache, one copy per app instance, gone on restart. A lock
# guards both dicts since FastAPI runs sync handlers in a threadpool,
# so concurrent requests can hit these together; a plain dict's
# check-then-set isn't atomic.
_lock = threading.Lock()
# Insertion-ordered, and relied upon: eviction pops the oldest entry, which
# for a plain dict is the one inserted longest ago.
_entries: dict[tuple[int, str, int], _CacheEntry] = {}
_scope_versions: dict[int, int] = {}


def _evict_locked() -> None:
    """Keep the cache bounded. Caller must hold _lock.

    Entries only ever left this cache by being read after they expired, so a
    question asked once and never repeated stayed resident for its full TTL,
    and one asked once per tenant across many tenants stayed forever in
    aggregate. On a 512MB instance that is a slow leak of whole answers and
    their source chunks, and bump_scope makes it worse rather than better:
    invalidated entries become unreachable under a stale scope version, so
    nothing ever reads them again and nothing ever removes them.

    Expired entries go first, since they are free. Only if that is not enough
    does it evict live ones, oldest-inserted first. That is not true LRU, it
    is FIFO: reads do not refresh position. Real LRU would need reordering on
    every read, and for an exact-match cache in front of a pipeline this
    expensive, the difference is not worth the extra work per request.
    """
    if len(_entries) <= settings.cache_max_entries:
        return

    now = time.monotonic()
    for key in [k for k, v in _entries.items() if v.expires_at < now]:
        del _entries[key]

    while len(_entries) > settings.cache_max_entries:
        _entries.pop(next(iter(_entries)))


def _make_key(tenant_id: int, question: str) -> tuple[int, str, int]:
    scope_version = _scope_versions.get(tenant_id, 0)
    return (tenant_id, normalize_question(question), scope_version)


def get_cached_answer(tenant_id: int, question: str) -> CachedAnswer | None:
    """Cache-aside read. Returns None on any miss (never cached, expired,
    or the tenant's document set changed since caching, see bump_scope),
    and the caller falls through to the real pipeline as if there were
    no cache."""
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
        _evict_locked()


def bump_scope(tenant_id: int) -> None:
    """Invalidates every cached answer for a tenant in O(1) by advancing
    its document-scope version rather than scanning for matching
    entries: old entries are keyed to the old version, so they go
    unreachable and age out via TTL.

    Call whenever the tenant's ready-document set changes, since a
    previously cached answer or refusal may no longer be correct.
    """
    with _lock:
        _scope_versions[tenant_id] = _scope_versions.get(tenant_id, 0) + 1
