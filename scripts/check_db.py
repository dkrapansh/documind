"""Answer one question: is this database alive, and if not, why not.

Written for the production outage where the API stopped responding entirely.
The start command coupled migrations to the server, so a database problem
killed the container before anything could report it (see scripts/start.sh).
This checks the database directly, from outside the app, and separates the
failure into a specific layer instead of one opaque "connection failed".

Usage:
    python -m scripts.check_db --url "postgresql+psycopg://..."
    python -m scripts.check_db                 # falls back to $DATABASE_URL

Never prints the password, so the output is safe to paste into a chat or an
issue.
"""
import argparse
import os
import socket
import sys
from urllib.parse import urlparse

# Hostname patterns for the managed Postgres providers this project has
# plausibly used. Which one it is changes the prognosis completely:
# a Render free database is DELETED at 30 days and the data is gone, while
# a Supabase free project is PAUSED after inactivity and restores intact
# from the dashboard. Same symptom, very different recovery.
_PROVIDERS = (
    ("supabase", ("supabase.co", "supabase.com", "pooler.supabase.com")),
    ("render", ("render.com", "oregon-postgres", "frankfurt-postgres", "singapore-postgres")),
    ("neon", ("neon.tech",)),
    ("railway", ("railway.app", "rlwy.net")),
    ("local", ("localhost", "127.0.0.1", "host.docker.internal")),
)

_PROVIDER_NOTES = {
    "supabase": (
        "Supabase free projects PAUSE after ~7 days of inactivity rather than being "
        "deleted. If this is unreachable, check the Supabase dashboard: a paused "
        "project restores from a button and the data is retained."
    ),
    "render": (
        "Render FREE Postgres instances EXPIRE and are DELETED 30 days after "
        "creation. If this is unreachable and the instance is gone from the Render "
        "dashboard, the data is not recoverable and a new database must be created."
    ),
    "neon": "Neon free projects suspend on idle and resume on the next connection.",
    "railway": "Check the Railway dashboard for a suspended or deleted service.",
    "local": "Local database. Start it with: docker compose up -d",
}

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"


def _report(status: str, label: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f": {detail}" if detail else ""))


def _identify_provider(host: str) -> str:
    lowered = host.lower()
    for name, patterns in _PROVIDERS:
        if any(pattern in lowered for pattern in patterns):
            return name
    return "unknown"


def _parse(url: str):
    # SQLAlchemy's driver suffix (postgresql+psycopg) is not a valid URL
    # scheme for urlparse's netloc handling, so normalise it first.
    parsed = urlparse(url.replace("postgresql+psycopg", "postgresql", 1))
    if not parsed.hostname:
        raise ValueError("no hostname found in the URL")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.url:
        print("No URL given. Pass --url or set DATABASE_URL.", file=sys.stderr)
        return 2

    try:
        parsed = _parse(args.url)
    except ValueError as exc:
        _report(FAIL, "parse URL", str(exc))
        return 1

    host = parsed.hostname
    port = parsed.port or 5432
    database = (parsed.path or "/").lstrip("/") or "(default)"
    provider = _identify_provider(host)

    print("=" * 62)
    print(f"host      {host}")
    print(f"port      {port}")
    print(f"database  {database}")
    print(f"user      {parsed.username or '(none)'}")
    print(f"provider  {provider}")
    print("=" * 62)
    if provider in _PROVIDER_NOTES:
        print(_PROVIDER_NOTES[provider])
        print("=" * 62)

    # 1. DNS. A provider that deleted the instance usually stops resolving
    # the hostname at all, which is the fastest signal that it is gone
    # rather than merely asleep or refusing connections.
    try:
        socket.getaddrinfo(host, port)
        _report(PASS, "DNS resolves")
    except socket.gaierror as exc:
        _report(FAIL, "DNS resolves", str(exc))
        print("\nThe hostname does not resolve. The database instance most likely no")
        print("longer exists. On Render free tier that is what a 30-day expiry looks like.")
        return 1

    # 2. TCP. Separates "host is there but nothing is listening" (deleted or
    # stopped) from "listening but rejecting us" (credentials, TLS, firewall).
    try:
        with socket.create_connection((host, port), timeout=10):
            _report(PASS, "TCP connect")
    except OSError as exc:
        _report(FAIL, "TCP connect", str(exc))
        print("\nThe host resolves but nothing accepted a connection on that port.")
        print("The instance is stopped, paused, deleted, or blocked by a firewall.")
        return 1

    # 3. Authenticate and run a real query.
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(args.url, connect_args={"connect_timeout": 10})
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version()")).scalar_one()
            _report(PASS, "authenticate", version.split(",")[0])

            has_vector = connection.execute(
                text("SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'")
            ).scalar_one()
            if has_vector:
                _report(PASS, "pgvector extension installed")
            else:
                _report(FAIL, "pgvector extension installed", "run: CREATE EXTENSION vector")

            # 4. Schema state. Distinguishes "empty database, never migrated"
            # from "migrated but behind this build" from "up to date".
            try:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
            except Exception:
                revision = None

            if revision is None:
                _report(WARN, "alembic revision", "no alembic_version table, never migrated")
            else:
                _report(PASS, "alembic revision", revision)

                try:
                    from alembic.config import Config
                    from alembic.script import ScriptDirectory

                    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    head = ScriptDirectory.from_config(
                        Config(os.path.join(root, "alembic.ini"))
                    ).get_current_head()
                    if revision == head:
                        _report(PASS, "schema matches this build")
                    else:
                        _report(FAIL, "schema matches this build", f"db={revision} head={head}")
                except Exception as exc:
                    _report(WARN, "compare to head revision", type(exc).__name__)

                # 5. Did the data survive. The number that matters after an
                # outage is whether the seeded demo corpus is still there,
                # since that is what the public demo serves.
                for table in ("tenants", "documents", "chunks"):
                    try:
                        count = connection.execute(
                            text(f"SELECT COUNT(*) FROM {table}")
                        ).scalar_one()
                        _report(PASS, f"rows in {table}", str(count))
                    except Exception as exc:
                        _report(WARN, f"rows in {table}", type(exc).__name__)
    except Exception as exc:
        _report(FAIL, "authenticate", f"{type(exc).__name__}: {exc}")
        print("\nThe port accepted a connection but the database refused it.")
        print("Usually a rotated password, a deleted role, or a TLS requirement.")
        return 1

    print("\nDatabase is reachable and usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
