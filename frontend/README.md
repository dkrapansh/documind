# DocuMind: landing page + live demo

A scroll-driven marketing page for [DocuMind](../README.md), a multi-tenant RAG document Q&A
API. Built with React + Vite and GSAP/ScrollTrigger, wired to the live backend for a working
upload → ask → grounded-answer demo, not a mock.

## Local run

```bash
npm install
npm run dev
```

Opens at `http://localhost:5173`.

## Environment variables

Copy `.env.example` to `.env` and fill in:

| Variable | Purpose |
|---|---|
| `VITE_API_BASE` | Base URL of the deployed DocuMind API (e.g. `https://documind-oyhv.onrender.com`). |
| `VITE_DEMO_API_KEY` | API key for a dedicated **demo tenant** the live Demo section calls. See below. |

## CORS: required before the demo works

The backend has no CORS configuration by default, so every browser call from this frontend gets
blocked until it's added. The fix lives in the main repo:

- `app/main.py`: adds `CORSMiddleware`, origins read from `settings.frontend_origins`
  (`app/config.py`), a comma-separated `FRONTEND_ORIGINS_RAW` env var (default
  `http://localhost:5173`).
- `app/api/routers/query.py`: the `GET /query/stream` SSE `sources` event now includes each
  chunk's `confidence`, matching `POST /query`. Without this the streaming demo can show source
  chunks but not their scores.

Both are already deployed to the live backend. Add this frontend's deployed origin to the
backend's `FRONTEND_ORIGINS_RAW` env var (comma-separated alongside `http://localhost:5173`) once
it has a real host, and redeploy the backend.

## Demo key: env var vs. proxy

The Demo section needs an API key to call the backend from the browser. Any key placed in client
JS is publicly readable and can spend real Gemini quota, so this project does **not** hardcode a
privileged key. Two options, in order of how this repo is set up:

1. **Env-var demo key (what's implemented here).** `VITE_DEMO_API_KEY` is baked in at build time
   and used for every visitor. It belongs to a **dedicated demo tenant** with a tight per-key
   rate limit (the backend already rate-limits per key, see `rate_limit_requests` /
   `rate_limit_window_seconds` in `app/config.py`) and a small Gemini budget you're comfortable
   losing to abuse. Simple, but the key is visible in the built JS bundle to anyone who looks.
2. **Serverless proxy (recommended for a real production demo).** A tiny function (Vercel/Netlify/
   Cloudflare Worker) that holds the key server-side, forwards `/query`, `/query/stream`, and
   `/documents` calls, and adds the `X-API-Key` header itself. The browser never sees the key.
   Not implemented here to keep the deliverable to a static frontend, but `src/api/client.js` is
   the only place that would need to change (point `VITE_API_BASE` at the proxy instead of the
   backend directly).

### Known limitation of the shared demo tenant

Every visitor shares the same tenant (and the same document corpus), because the backend scopes
retrieval by tenant, not by browser session. If someone uploads their own file, later visitors'
questions can retrieve chunks from it too. Fine for a portfolio demo; not something you'd want for
a real multi-user product without adding per-session scoping on the backend.

## Seeding the demo tenant

The Demo section expects the tenant behind `VITE_DEMO_API_KEY` to already have at least one
`ready` document, that's what lets a first-time visitor ask a question immediately instead of
uploading first. The live demo tenant is already seeded with a sample Northwind employee handbook.
To (re)seed it, e.g. after rotating the key:

```bash
curl -X POST https://<api-base>/auth/keys -H "Content-Type: application/json" \
  -d '{"tenant_name":"demo"}'
# -> {"api_key": "...", "tenant_id": ...}

curl -X POST https://<api-base>/documents -H "X-API-Key: <api_key>" \
  -F "file=@northwind-employee-handbook.txt"
```

Poll `GET /documents/{id}` until `status` is `ready`, then put `api_key` in `VITE_DEMO_API_KEY`.

## Cold starts

The backend runs on Render's free tier, which sleeps after 15 minutes idle and takes 30-50s to
wake on the first request. `src/api/client.js` races every request against a short timeout and
surfaces a "waking the demo up" state via `onColdStart` instead of a hung spinner, see
`Demo.jsx`.

## Citation highlighting is a heuristic, not a backend guarantee

The backend doesn't return which part of the answer came from which chunk, only the source
chunks themselves. `src/lib/citationHighlight.js` looks for the longest verbatim overlap between
the streamed answer and each source chunk and highlights it client-side. It's a presentation
layer on top of always-accurate source cards, not a claim the model told us what it cited;
answers that paraphrase instead of quoting just render plain. The Hero section's traced-answer
card is a separate, hardcoded illustration and isn't affected by this.

## Deploy

This is a static build (`npm run build` → `dist/`); any static host works (Vercel, Netlify,
Cloudflare Pages, GitHub Pages). Point it at the live API via `VITE_API_BASE` and set
`VITE_DEMO_API_KEY` as a build-time environment variable on the host. Remember to add the
deployed origin to the backend's `FRONTEND_ORIGINS_RAW` and redeploy the backend, or every request
will fail CORS.
