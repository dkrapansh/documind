# DocuMind

A deployed, multi-tenant document Q&A API with hybrid retrieval (dense + BM25 +
cross-encoder rerank), an offline RAGAS evaluation harness, and full request
observability — built as a modular monolith.

## Status

🚧 Under active development. Week 1 (skeleton, DB, auth) complete.

## Stack

FastAPI · PostgreSQL + pgvector · SQLAlchemy + Alembic · LangChain (thin use) ·
RAGAS · Docker

## Architecture

One FastAPI process, layered internally:

```
Client → [Middleware: correlation-id → auth → rate-limit] → Router → Service → Repository → PostgreSQL (+pgvector)
                                                                    → Clients → LLM / Embedding / Rerank APIs
```

## Running locally

```bash
docker compose up -d          # starts Postgres + pgvector on port 5433
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Visit `http://localhost:8000/docs` for interactive Swagger UI.

## Running tests

```bash
pytest -v
```

Tests run against a separate `documind_test` database (see `.env.test`), never
against the dev database.

## Implemented so far

- [x] FastAPI skeleton, Docker Compose (Postgres+pgvector), `/health`
- [x] Full schema (6 tables) via Alembic migrations
- [x] API-key issuance with SHA-256 hashing (raw key never stored)
- [x] Middleware: correlation-id, API-key auth enforcement, per-key rate limiting
- [x] Custom exception hierarchy mapped to HTTP responses
- [x] pytest suite covering auth (401), rate-limiting (429), key issuance

## Not yet built

Document ingestion, embeddings, retrieval, evaluation harness, streaming,
caching, deployment. See commit history for day-by-day progress.