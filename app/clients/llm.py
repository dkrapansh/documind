from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=types.HttpOptions(timeout=30_000),
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4)
)
def generate_answer(messages: list[dict]) -> str:
    """Run a chat completion over the given messages and return the answer text.

    answering.py builds OpenAI-style {"role": ..., "content": ...} dicts;
    Gemini takes the system prompt as a separate system_instruction rather
    than a role inside the content list, so it's extracted here rather
    than changing the caller.

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on
    transient failures — same resilience pattern as clients/embeddings.py,
    with a longer timeout since a full answer takes longer to generate
    than a single embedding call.
    """
    system_instruction = next(m["content"] for m in messages if m["role"] == "system")
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    response = _client.models.generate_content(
        model=settings.gemini_llm_model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.0,
        ),
    )
    return response.text
