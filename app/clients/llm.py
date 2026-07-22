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

    Retries up to 8 times with exponential backoff (2s, 4s, 8s, 16s, then
    30s capped) on transient failures — same resilience pattern as
    clients/embeddings.py, with a longer timeout since a full answer
    takes longer to generate than a single embedding call. Recalibrated
    twice against real Gemini free-tier 429s: first from 3 attempts/4s-max
    (couldn't outlast a single ~23s RetryInfo.retryDelay window at all),
    then from 5 to 8 attempts after two back-to-back eval harness runs
    still occasionally exhausted 5 attempts' ~60s total budget when the
    per-minute window was already under pressure from the prior run.
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
    """Same call as generate_answer, but yields text deltas as they
    arrive instead of blocking for the full answer - powers GET
    /query/stream's Server-Sent Events response.

    Deliberately has no @retry: once the first chunk has reached the
    caller (routers/query.py, already forwarding it to an open SSE
    connection), transparently retrying the whole request from scratch
    would either duplicate already-streamed text or require buffering
    everything anyway - defeating the point of streaming. A dropped
    connection mid-stream surfaces as an exception the SSE endpoint turns
    into a terminal error event instead.
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
