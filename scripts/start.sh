#!/bin/sh
# Container entrypoint.
#
# The previous start command was:
#     alembic upgrade head && uvicorn app.main:app ...
#
# The `&&` is what took production down. Any database problem (an expired
# free-tier Postgres, a rotated credential, a network blip) made Alembic
# exit non-zero, so uvicorn never ran, the container died, and Render
# marked the service failed. Nothing was left alive to report why: the
# health endpoint cannot answer when the process serving it never started.
# Externally that is indistinguishable from a hung cold start.
#
# So migrations no longer gate the server. They still run, and a failure is
# still loud, but uvicorn starts either way. A booted instance answering
# /health/live and reporting "migrations: pending" or "database: error" on
# /health/ready is diagnosable in seconds. A dead container is not.
#
# Serving on an unmigrated schema is the risk this trades for, and it is
# covered: /health/ready compares the database's Alembic revision against
# the code's head revision and reports not-ready on a mismatch, so a
# half-deployed instance fails its readiness check instead of quietly
# serving errors.
#
# On a paid Render instance this belongs in `preDeployCommand` instead,
# where a failed migration aborts the deploy and leaves the previous
# version serving. That is strictly better and is not available on free.

set -u

echo "startup: running database migrations"
if alembic upgrade head; then
    echo "startup: migrations up to date"
else
    echo "FATAL: alembic upgrade head failed. Starting the API anyway so /health/ready can report why." >&2
    echo "FATAL: check DATABASE_URL and that the database is reachable and still exists." >&2
fi

echo "startup: launching uvicorn on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
