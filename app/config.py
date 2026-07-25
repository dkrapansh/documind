from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str

    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    openai_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"

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

    # Exact-match query cache (services/query_cache.py). 5 minutes is a
    # starting guess, not tuned against real traffic like confidence_threshold
    # was - invalidation on document change is what keeps this safe even if
    # the TTL is generous.
    cache_ttl_seconds: int = 300
settings = Settings()