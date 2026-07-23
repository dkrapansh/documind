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
    # gemini-3.6-flash was the original choice, but its free tier caps at
    # 20 generate_content calls/day - nowhere near enough for a 30-item
    # batch eval plus RAGAS's own judge calls on top, run more than once.
    # Switched to gemini-3.5-flash-lite for its much higher free daily
    # quota (500/day) - then switched again to gemini-3.1-flash-lite after
    # exhausting THAT 500/day quota via repeated eval harness debugging
    # runs in one session. Each Gemini model has its own separate daily
    # quota bucket (confirmed live: gemini-3.5-flash-lite returning 429
    # RESOURCE_EXHAUSTED while gemini-3.1-flash-lite succeeded, same
    # minute, same key) - worth remembering next time this one runs dry.
    gemini_llm_model: str = "gemini-3.1-flash-lite"

    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Raw cross-encoder logit, not a probability or a 0-1 score. Originally
    # -6.0, from a five-example manual probe (exact match ~+5.6, correct
    # paraphrase ~-2.4, irrelevant ~-11; 0.0 wrongly refused the
    # paraphrased-but-correct case). Re-tuned to -3.0 for real, per Day
    # 26's design, against the full 30-item golden dataset via the eval
    # harness (eval/run_eval.py): -6.0 baseline scored 3/6 (50%) correct
    # refusals on expected_refusal questions; -3.0 scored 5/6 (83%), with
    # faithfulness (1.0), answer_relevancy (0.83), and context_precision
    # (0.79) on the 24 answerable items completely unchanged between the
    # two runs (see eval/RESULTS.md for the full before/after).
    confidence_threshold: float = -3.0

    storage_dir: str = "storage"

    # Exact-match query cache (services/query_cache.py). 5 minutes is a
    # starting guess, not tuned against real traffic like confidence_threshold
    # was - invalidation on document change is what keeps this safe even if
    # the TTL is generous.
    cache_ttl_seconds: int = 300
settings = Settings()