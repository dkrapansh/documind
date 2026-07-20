from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

_client = OpenAI(api_key=settings.openai_api_key, timeout=30.0)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4)
)
def generate_answer(messages: list[dict]) -> str:
    """Run a chat completion over the given messages and return the answer text.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on
    transient failures — same resilience pattern as clients/embeddings.py,
    with a longer timeout since a full answer takes longer to generate
    than a single embedding call.
    """
    response = _client.chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        temperature=0.0,
    )
    return response.choices[0].message.content
