from openai import OpenAI
from  tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
_client = OpenAI(api_key=settings.openai_api_key, timeout=10.0)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=3)
)
def embed_text(text: str) -> list[float]:
    """Turn a string into a 1536-dim embedding vector via OpenAI.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on
    transient failures — a single dropped connection during a 50-page
    ingestion job shouldn't fail the whole document.
    """
    response = _client.embeddings.create(
        model=settings.embedding_model,
        input=text,
    )
    return response.data[0].embedding