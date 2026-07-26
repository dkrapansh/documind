# DocuMind: landing page + live demo

A scroll-driven marketing page for [DocuMind](../README.md), a multi-tenant RAG document Q&A
API. Built with React + Vite and GSAP/ScrollTrigger, wired to the live backend for a working
upload → ask → grounded-answer demo, not a mock.

## Architecture: same-origin proxy, no client-visible API key

This is a Vercel project, not just a static site: `api/` holds Node.js serverless functions that
sit between the browser and the DocuMind backend. The browser never talks to the backend directly
and never holds an API key.

```
browser --(same-origin, cookie)--> /api/* (Vercel function) --(X-API-Key)--> DocuMind backend
```

- `api/documents.js` proxies list / status / upload (`GET`, `GET ?id=`, `POST`).
- `api/query-stream.js` proxies the SSE streaming endpoint, relaying the response body through
  unmodified so tokens still arrive as they're generated.
- `api/_lib/session.js` is shared by both: on a request with no `dm_session` cookie, it calls the
  backend's `POST /auth/demo-session` to mint a fresh, isolated, throwaway tenant for that visitor,
  then sets the raw key as an `httpOnly`, `Secure`, `SameSite=Strict` cookie. Client JS can't read
  it; it's only ever forwarded server-side as the `X-API-Key` header on the next backend call.

Both functions default to the **Node.js runtime, not Edge**: Edge Functions have a hard,
non-configurable 25s timeout, shorter than a Render free-tier cold start (30-50s). Node.js
Functions default to 300s (Fluid Compute, all plans including Hobby) and stream just as well.
`vercel.json` also sets an explicit 60s `maxDuration`.

### Why this exists (not a design choice made in a vacuum)

The first version of this demo used one shared API key, baked into the client bundle via a
`VITE_DEMO_API_KEY` env var. That key was trivially readable in the deployed JS, and because the
backend scopes retrieval by tenant rather than by browser session, everyone shared one tenant: any
visitor's uploaded document was retrievable by any other visitor's questions. This was caught
during testing (a real document got uploaded and its content surfaced in an unrelated query).
Containment at the time: the leaked key was revoked (`POST /auth/keys/revoke`, `app/api/routers/auth.py`)
and the exposed document deleted (`DELETE /documents/{id}`, `app/api/routers/documents.py`). Both
endpoints exist because that incident needed them, and they stay useful for tenant cleanup
generally. This proxy plus per-visitor tenant design is the actual fix, not just the patch.

### Per-visitor isolation, and how it stays cheap

`POST /auth/demo-session` (backend) doesn't just mint a bare tenant: it clones the seed corpus
(the sample Northwind handbook) into it: existing chunk text and embeddings are copied by value,
with **zero embedding-API calls**, so a brand-new visitor can ask the "answerable" preset question
immediately without waiting on ingestion. See `app/services/demo_seed.py` in the backend.

Ephemeral tenants are swept once older than `settings.ephemeral_tenant_ttl_minutes` (default 60).
The sweep runs lazily inside `POST /auth/demo-session` itself (no cron needed); see
`app/services/tenant_cleanup.py`.

## Local run

```bash
npm install
npm run dev
```

Opens at `http://localhost:5173`, but this only serves the static UI. The `/api/*` proxy
functions are Vercel-specific and **do not run** under plain `vite dev`; any live-demo action will
show the "couldn't reach the demo" state. To test the full flow locally, use the Vercel CLI instead:

```bash
npx vercel dev
```

This serves the Vite app and the `/api/*` functions together, reading env vars from `.env`.

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Purpose |
|---|---|
| `DOCUMIND_API_BASE` | Base URL of the deployed DocuMind API. **No `VITE_` prefix**: this must stay server-only. Read via `process.env` inside `api/*.js`, never inlined into the client bundle. |
| `DOCUMIND_PROXY_SHARED_SECRET` | Must match the backend's `DEMO_PROXY_SHARED_SECRET`. Lets the backend's per-IP rate limiter on `POST /auth/demo-session` trust the real visitor IP this proxy forwards, instead of rate-limiting every visitor together under Vercel's own egress IP. Optional for local dev; without it the backend just falls back to its own raw TCP peer address. |

There is no client-side API key anywhere in this project. Don't add one back.

## CORS

Not needed for the deployed proxy flow: `/api/*` calls are same-origin. The backend's
`CORSMiddleware` (`app/main.py`, allowlist via `FRONTEND_ORIGINS_RAW`) still exists for direct
`npm run dev` testing against the live backend and is harmless to leave, but production traffic
never needs it now.

## Cold starts

The backend runs on Render's free tier, which sleeps after 15 minutes idle and takes 30-50s to
wake on the first request. `src/api/client.js` races every request against a short timeout and
surfaces a "waking the demo up" state via `onColdStart` instead of a hung spinner (see
`Demo.jsx`). The proxy functions' 60s `maxDuration` covers this.

## Citation highlighting is a heuristic, not a backend guarantee

The backend doesn't return which part of the answer came from which chunk, only the source
chunks themselves. `src/lib/citationHighlight.js` looks for the longest verbatim overlap between
the streamed answer and each source chunk and highlights it client-side. It's a presentation
layer on top of always-accurate source cards, not a claim the model told us what it cited;
answers that paraphrase instead of quoting just render plain. The Hero section's traced-answer
card is a separate, hardcoded illustration and isn't affected by this.

## Deploy

This has to be deployed as a **Vercel project** (or an equivalent platform with the same
serverless-function-alongside-static-build model). A plain static host (GitHub Pages, a CDN
bucket) can't run the `api/` proxy functions the demo depends on.

```bash
npx vercel link
npx vercel env add DOCUMIND_API_BASE production   # and preview, development
npx vercel --prod
```

If you fork this to a domain other than `*.vercel.app`, nothing on the backend needs to change:
the proxy calls the backend server-side, so the backend's CORS allowlist is irrelevant to it.
