// Every call here is same-origin, to this app's own /api/* proxy
// functions (see frontend/api/), not directly to the DocuMind backend.
// The proxy mints a per-visitor ephemeral tenant server-side and holds
// its key in an httpOnly cookie the browser sends automatically - no API
// key is ever readable from client JS. See frontend/api/_lib/session.js
// and frontend/README.md for why (a single shared, client-visible demo
// key previously let any visitor read any other visitor's uploads).

const COLD_START_MESSAGE =
  "Couldn't reach the demo. The free-tier host may be waking up (this can take 30-50s). Retrying...";

class ApiError extends Error {
  constructor(message, { status, coldStart = false } = {}) {
    super(message);
    this.status = status;
    this.coldStart = coldStart;
  }
}

/**
 * Render free-tier instances sleep after idle and take 30-50s to wake on
 * the first request. A plain fetch would just hang from the caller's
 * perspective, so this races the request against a short timeout and lets
 * the caller show a "waking up" state instead of a dead spinner.
 */
async function fetchWithWakeHint(url, options, { onColdStart, wakeTimeoutMs = 6000 } = {}) {
  const controller = new AbortController();
  const hintTimer = setTimeout(() => onColdStart?.(), wakeTimeoutMs);

  try {
    const res = await fetch(url, { ...options, signal: options?.signal ?? controller.signal });
    return res;
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new ApiError(COLD_START_MESSAGE, { coldStart: true });
  } finally {
    clearTimeout(hintTimer);
  }
}

async function parseJsonOrThrow(res) {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(detail, { status: res.status });
  }
  return res.json();
}

export async function uploadDocument(file, opts = {}) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetchWithWakeHint("/api/documents", { method: "POST", body: form }, opts);
  return parseJsonOrThrow(res);
}

export async function getDocument(id, opts = {}) {
  const res = await fetchWithWakeHint(`/api/documents?id=${id}`, {}, opts);
  return parseJsonOrThrow(res);
}

export async function listDocuments(opts = {}) {
  const res = await fetchWithWakeHint("/api/documents", {}, opts);
  return parseJsonOrThrow(res);
}

/**
 * Polls GET /api/documents?id={id} every ~1.5s until status is "ready" or
 * "failed". Returns the final document. `onTick` fires on every poll so
 * the caller can show interim state (chunk_count, "processing", ...).
 */
export async function pollDocumentUntilReady(id, { onTick, intervalMs = 1500, timeoutMs = 120000 } = {}) {
  const startedAt = Date.now();
  for (;;) {
    const doc = await getDocument(id);
    onTick?.(doc);
    if (doc.status === "ready" || doc.status === "failed") return doc;
    if (Date.now() - startedAt > timeoutMs) {
      throw new ApiError("Document is taking longer than expected to process.");
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/**
 * Streams GET /api/query-stream via fetch + ReadableStream instead of
 * EventSource, because EventSource can't send the cookie-derived auth
 * this proxy relies on for anything but simple GETs in some browsers,
 * and can't be aborted mid-stream either. SSE frames
 * ("event: name\ndata: json\n\n") are parsed by hand off the decoded
 * chunk buffer.
 *
 * handlers: { onSources, onSession, onDelta, onDone, onColdStart, onError }
 * Returns an abort() function.
 */
export function streamQuery(question, { sessionId, ...handlers } = {}) {
  const controller = new AbortController();
  const params = new URLSearchParams({ question });
  if (sessionId) params.set("session_id", sessionId);

  (async () => {
    let res;
    try {
      res = await fetchWithWakeHint(
        `/api/query-stream?${params.toString()}`,
        { signal: controller.signal },
        { onColdStart: handlers.onColdStart, wakeTimeoutMs: 6000 }
      );
    } catch (err) {
      if (err.name !== "AbortError") handlers.onError?.(err);
      return;
    }

    if (!res.ok || !res.body) {
      const err = await parseJsonOrThrow(res).catch((e) => e);
      handlers.onError?.(err instanceof Error ? err : new ApiError("Stream failed to start"));
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          dispatchFrame(frame, handlers);
        }
      }
      handlers.onDone?.();
    } catch (err) {
      if (err.name !== "AbortError") handlers.onError?.(err);
    }
  })();

  return () => controller.abort();
}

function dispatchFrame(frame, handlers) {
  const lines = frame.split("\n");
  let event = "message";
  let data = "";
  for (const line of lines) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) data += line.slice(6);
  }
  if (!data) return;

  let payload;
  try {
    payload = JSON.parse(data);
  } catch {
    return;
  }

  if (event === "sources") handlers.onSources?.(payload);
  else if (event === "session") handlers.onSession?.(payload.session_id);
  else if (event === "delta") handlers.onDelta?.(payload.text);
  else if (event === "error") handlers.onError?.(new ApiError(payload.message));
  else if (event === "done") handlers.onDone?.();
}

export { ApiError, COLD_START_MESSAGE };
