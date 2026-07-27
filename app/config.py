from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str

    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    # POST /auth/keys is unauthenticated by necessity (nothing exists yet
    # to authenticate with), same as /auth/demo-session, so it needs its
    # own per-IP cap independent of RateLimitMiddleware (which only
    # limits requests that already resolved an api_key_id). Otherwise a
    # script can mint unlimited tenants+keys for free.
    auth_keys_rate_limit: int = 20
    auth_keys_rate_limit_window_seconds: int = 3600

    gemini_api_key: str
    gemini_embedding_model: str = "gemini-embedding-001"
    # gemini-3.6-flash's free tier caps at 20 calls/day, not enough for
    # a 30-item eval run. gemini-3.5-flash-lite (500/day) then also got
    # exhausted by repeated eval debugging in one session. Each Gemini
    # model has its own separate daily quota bucket, confirmed live, so
    # switching models (not waiting) is the fix when this one runs dry.
    gemini_llm_model: str = "gemini-3.1-flash-lite"

    reranker_model: str = "ms-marco-MiniLM-L-12-v2"
    # Sigmoid/softmax score [0, 1] from flashrank, not a raw logit.
    # First tuned -6.0 -> -3.0 against the old CrossEncoder's raw-logit
    # scale (30-item golden dataset, refusal accuracy 50% -> 83%,
    # faithfulness/relevancy/precision unchanged). Retuned to 0.7 after
    # the flashrank swap changed the score scale entirely: a local
    # probe found expected_refusal items scoring <=0.405 and answerable
    # items >=0.909, so 0.7 sits centered in that gap. Full numbers in
    # eval/RESULTS.md.
    confidence_threshold: float = 0.7

    storage_dir: str = "storage"

    # POST /documents has no framework-level body cap on the backend
    # itself (the Vercel proxy's 4.5MB request limit only covers the
    # frontend demo path, not direct callers of the Render API), so this
    # bounds it server-side. 20MB comfortably covers real handbook-sized
    # .txt/.pdf/.docx uploads.
    max_upload_size_bytes: int = 20 * 1024 * 1024

    # Exact-match query cache (services/query_cache.py). 5 minutes is a
    # starting guess, not tuned against real traffic like confidence_threshold
    # was - invalidation on document change is what keeps this safe even if
    # the TTL is generous.
    cache_ttl_seconds: int = 300

    # Comma-separated allowlist for CORSMiddleware, not a JSON list - Render's
    # env var UI is plain text fields, so this stays copy-pasteable there.
    frontend_origins_raw: str = "http://localhost:5173"

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins_raw.split(",") if origin.strip()]

    # POST /auth/demo-session mints a scoped, throwaway tenant per visitor
    # for the public landing-page demo (see PROJECT_CONTEXT for the
    # incident that led to this: a single shared demo key let any visitor
    # read any other visitor's uploaded documents). Swept once older than
    # this so the demo tenant pool doesn't grow forever.
    ephemeral_tenant_ttl_minutes: int = 60
    # Per-IP cap on /auth/demo-session, since it's unauthenticated by
    # necessity (nothing exists yet to authenticate with). Same in-memory,
    # single-instance-only limiter as RateLimitMiddleware - acceptable on
    # Render's free tier (one instance), and callers behind a shared NAT
    # or the frontend's own proxy hop just share one bucket.
    demo_session_rate_limit: int = 20
    demo_session_rate_limit_window_seconds: int = 3600
    # Tenant whose ready documents get cloned (chunks + embeddings, no
    # re-embedding) into every new ephemeral demo tenant - see
    # services/demo_seed.py.
    seed_tenant_name: str = "demo"
    # Hard ceiling on concurrently live (within-TTL) ephemeral tenants.
    # The per-IP demo_session_rate_limit bounds one visitor's mint rate,
    # but not the total number of distinct visitors inside one TTL
    # window - each mint clones the seed corpus by value, so unbounded
    # concurrent tenants is unbounded storage growth. Checked after the
    # lazy sweep, so this counts tenants genuinely still alive, not ones
    # merely awaiting cleanup.
    max_live_ephemeral_tenants: int = 200

    # Shared secret with frontend/api/ (Vercel), same value as its
    # DOCUMIND_PROXY_SHARED_SECRET. Lets auth.py's _client_ip trust a
    # forwarded visitor IP only when it really came through the proxy,
    # since a direct caller could set that header to anything. None
    # (local dev default) means it's never trusted.
    demo_proxy_shared_secret: str | None = None
settings = Settings()