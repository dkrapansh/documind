from collections.abc import Iterator

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

_client = genai.Client(
    api_key=settings.gemini_api_key,
    http_options=types.HttpOptions(timeout=30_000),
)

def _split_messages(messages: list[dict]) -> tuple[str, str]:
    """answering.py builds OpenAI-style {"role": ..., "content": ...}
    dicts; Gemini takes the system prompt as a separate
    system_instruction rather than a role inside the content list, so
    it's split out here rather than changing the caller."""
    system_instruction = next(m["content"] for m in messages if m["role"] == "system")
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    return system_instruction, user_content

@retry(
    stop=stop_after_attempt(8),
    wait=wait_exponential(multiplier=1, min=2, max=30)
)
def generate_answer(messages: list[dict]) -> str:
    """Run a chat completion over the given messages and return the answer text.

    Retries up to 8 times with exponential backoff (2s-30s), same pattern
    as embeddings.py. Tuned twice against real Gemini free-tier 429s: 3
    attempts couldn't outlast a single retry window, 5 still ran out
    under back-to-back eval harness load.
    """
    system_instruction, user_content = _split_messages(messages)

    response = _client.models.generate_content(
        model=settings.gemini_llm_model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.0,
        ),
    )
    return response.text


def stream_answer(messages: list[dict]) -> Iterator[str]:
    """Same call as generate_answer, but yields text deltas as they arrive
    instead of blocking for the full answer, powering GET /query/stream's
    SSE response.

    No @retry here on purpose: once the first chunk reaches an open SSE
    connection, retrying from scratch would duplicate streamed text or
    require buffering everything anyway. A dropped connection mid-stream
    surfaces as an exception instead.
    """
    system_instruction, user_content = _split_messages(messages)

    stream = _client.models.generate_content_stream(
        model=settings.gemini_llm_model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.0,
        ),
    )
    for chunk in stream:
        if chunk.text:
            yield chunk.text
