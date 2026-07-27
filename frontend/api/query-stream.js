import { Readable } from "node:stream";
import { getSessionKey, attachSessionCookie, BACKEND } from "./_lib/session.js";

// Same runtime reasoning as documents.js: default Node.js (Fluid
// Compute, 300s), not edge (hard 25s cap, shorter than a Render
// free-tier cold start).
//
// Proxies GET /api/query-stream to the backend's SSE endpoint, relaying
// the response body stream through unmodified so tokens still arrive to
// the browser as they're generated rather than being buffered here.
export default async function handler(req, res) {
  let session;
  try {
    session = await getSessionKey(req);
  } catch (err) {
    res.status(err.status ?? 502).json({ detail: err.message });
    return;
  }

  const url = new URL(req.url, "http://internal");
  const target = `${BACKEND}/query/stream?${url.searchParams.toString()}`;

  const upstream = await fetch(target, {
    headers: { "X-API-Key": session.key },
  });

  if (session.isNew) attachSessionCookie(res, session.key);
  res.status(upstream.status);
  res.setHeader("Content-Type", upstream.headers.get("content-type") ?? "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  if (!upstream.body) {
    res.end();
    return;
  }
  Readable.fromWeb(upstream.body).pipe(res);
}
