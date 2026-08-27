from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import settings

# Pool sizing and timeouts are explicit rather than inherited from
# SQLAlchemy's defaults. Each in-flight request briefly holds two
# connections (AuthMiddleware opens its own session for the API key
# lookup before the route's get_db opens another), and background jobs
# hold one for the whole job, so the effective concurrency ceiling is
# lower than the pool size suggests.
#
# connect_timeout bounds how long a new connection waits on an
# unreachable database, and statement_timeout is a Postgres-side ceiling
# so one wedged query cannot pin a connection, and therefore a request
# thread, indefinitely. Long-running work (ingestion, eval) is a sequence
# of short statements around slow Python, so neither bound cuts it short.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout_seconds,
    connect_args={
        "connect_timeout": settings.db_connect_timeout_seconds,
        "options": f"-c statement_timeout={settings.db_statement_timeout_seconds * 1000}",
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def check_connection() -> None:
    """Round-trip a trivial query, for GET /health/ready.

    Raises whatever SQLAlchemy raises. The caller decides how to report
    it, since a readiness probe wants the failure classified, not
    swallowed. Deliberately not cached: a readiness probe that reports a
    stale "ok" is worse than one that costs a round trip.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
