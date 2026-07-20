from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str

    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60

    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"
    llm_model: str = "gpt-4o-mini"

    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    # Raw cross-encoder logit, not a probability or a 0-1 score. A quick
    # manual probe against this model: a clear, exact-wording match
    # scored +5.6; a correct but paraphrased match (no shared keywords)
    # scored -2.4; clearly irrelevant text scored around -11. 0.0 would
    # wrongly refuse the paraphrased-but-correct case, so -6.0 sits in
    # the gap instead - biased toward answering over refusing. This is
    # a provisional value; Day 26's eval harness re-tunes it for real
    # against the golden dataset rather than a five-example probe.
    confidence_threshold: float = -6.0

    storage_dir: str = "storage"
settings = Settings()