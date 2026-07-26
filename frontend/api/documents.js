import { Readable } from "node:stream";
import { getSessionKey, attachSessionCookie, BACKEND } from "./_lib/session.js";

async function bufferBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  return Buffer.concat(chunks);
}

// Classic Vercel Node.js function (req, res) signature, not the Web
// Request/Response signature - kept simple and guaranteed-stable for a
// plain (non-framework) /api directory. Default Node.js runtime, not
// edge: edge functions have a hard 25s timeout, shorter than Render
// free-tier cold starts (30-50s); Node.js Functions default to 300s.
//
// Proxies GET /api/documents (list), GET /api/documents?id=123
// (status), and POST /api/documents (upload) to the backend, injecting
// the visitor's session key server-side. Query-string id instead of a
// dynamic /api/documents/[id] route keeps this to one function.
export default async function handler(req, res) {
  let session;
  try {
    session = await getSessionKey(req);
  } catch (err) {
    res.status(502).json({ detail: err.message });
    return;
  }

  const url = new URL(req.url, "http://internal");
  const id = url.searchParams.get("id");
  const target = id ? `${BACKEND}/documents/${id}` : `${BACKEND}/documents`;

  // Buffered, not streamed: Vercel's local dev server has already
  // consumed part of the incoming request stream by the time this
  // handler runs, which breaks passing `req` straight through as a
  // fetch body. Uploads here are small handbook-sized files anyway,
  // well under Vercel's 4.5MB request body cap.
  const body = req.method === "POST" ? await bufferBody(req) : undefined;

  const upstream = await fetch(target, {
    method: req.method,
    headers: {
      "X-API-Key": session.key,
      ...(req.headers["content-type"] ? { "Content-Type": req.headers["content-type"] } : {}),
    },
    body,
  });

  if (session.isNew) attachSessionCookie(res, session.key);
  res.status(upstream.status);
  res.setHeader("Content-Type", upstream.headers.get("content-type") ?? "application/json");
  if (!upstream.body) {
    res.end();
    return;
  }
  Readable.fromWeb(upstream.body).pipe(res);
}
