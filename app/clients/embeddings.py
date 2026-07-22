from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=types.HttpOptions(timeout=10_000),
)

@retry(
    stop=stop_after_attempt(8),
    wait=wait_exponential(multiplier=1, min=2, max=30)
)
def embed_text(text: str) -> list[float]:
    """Turn a string into a 1536-dim embedding vector via Gemini.

    output_dimensionality=1536 is pinned explicitly: gemini-embedding-001
    defaults to 3072 dims, which would not fit the existing
    chunks.embedding Vector(1536) column.

    Retries up to 8 times with exponential backoff (2s, 4s, 8s, 16s, then
    30s capped) on transient failures - recalibrated alongside
    clients/llm.py, twice, against real Gemini free-tier 429s (see that
    module's docstring for the two incidents that drove each bump).
    """
    response = _client.models.embed_content(
        model=settings.gemini_embedding_model,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=1536),
    )
    return response.embeddings[0].values
