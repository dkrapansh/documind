import logging
from pathlib import Path

from app import APP_VERSION
from app.config import settings
from app.db.session import check_connection, engine

logger = logging.getLogger(__name__)

# Dependencies whose failure means this instance cannot serve a query at
# all, so readiness reports "not ready" and the caller gets a 503. The
# reranker is deliberately not in here: it loads lazily on first use by
# design, so "not loaded yet" is a normal state for a freshly booted
# instance, not a reason to refuse traffic.
_REQUIRED_FOR_TRAFFIC = ("database", "migrations")

_ALEMBIC_INI = Path(__file__).resolve().parent.parent.parent / "alembic.ini"


def liveness() -> dict:
    """Proves the process is alive and serving. Touches nothing external.

    This is what the platform health check should point at. The previous
    /health endpoint queried nothing either, but it also reported nothing,
    so it could not distinguish "up" from "up but unable to work". Keeping
    liveness dependency-free is what lets readiness be honest: an instance
    with a dead database stays alive to explain why, instead of being
    killed and restarted into the same failure.
    """
    return {"status": "alive", "version": APP_VERSION, "git_sha": settings.git_sha}


def _database_status() -> dict:
    try:
        check_connection()
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("readiness: database check failed")
        # The exception type only. Its message can carry the host, the
        # user, and occasionally the password from a connection URL, and
        # this endpoint is unauthenticated.
        return {"status": "error", "error_type": type(exc).__name__}


def _migrations_status() -> dict:
    """Compares the schema revision the database is actually on against
    the head revision in this build's alembic/versions directory.

    This is what makes scripts/start.sh safe. Since a failed migration no
    longer stops the server (a dead container cannot explain itself), an
    instance can now boot against a schema its code does not expect. That
    is a real risk, and this is the check that catches it: a mismatch
    reports not-ready, so a half-deployed instance fails readiness loudly
    instead of quietly serving errors on missing columns.

    It also catches the reverse, a deployment/runtime mismatch where the
    database was migrated by a newer build than the one running here.
    """
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI)))
        head = script.get_current_head()

        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()

        if current == head:
            return {"status": "ok", "revision": current}
        return {"status": "pending", "revision": current, "head_revision": head}
    except Exception as exc:
        logger.exception("readiness: migration revision check failed")
        return {"status": "error", "error_type": type(exc).__name__}


def _provider_status(api_key: str | None, model: str) -> dict:
    """Configuration check, not a liveness call. Reaching out to Gemini
    here would make every readiness probe cost quota and inherit that
    API's latency, which is exactly the coupling a readiness probe is
    supposed to avoid. Reports the model name (public) and never the key.
    """
    return {"status": "configured" if api_key else "not_configured", "model": model}


def _reranker_status() -> dict:
    """Reports whether the model is already resident, without loading it.

    Importing the module is cheap; _get_ranker() is not, and calling it
    here would download the model from a third-party CDN on the first
    health check after every restart.
    """
    from app.clients import reranker

    return {
        "status": "loaded" if reranker._ranker is not None else "not_loaded",
        "model": settings.reranker_model,
    }


def readiness() -> tuple[bool, dict]:
    """Returns (ready, payload). Ready means every dependency required to
    actually serve a query is healthy, which is a stricter claim than
    liveness and a different question from "did the process start".

    Nothing here returns a secret: no connection string, no API key, no
    header values. The model names and the git SHA are safe to expose and
    are the two things most often needed to explain a production
    difference between two instances.
    """
    dependencies = {
        "database": _database_status(),
        "migrations": _migrations_status(),
        "embedding_provider": _provider_status(
            settings.gemini_api_key, settings.gemini_embedding_model
        ),
        "generation_provider": _provider_status(
            settings.gemini_api_key, settings.gemini_llm_model
        ),
        "reranker": _reranker_status(),
    }

    ready = all(
        dependencies[name]["status"] not in ("error", "not_configured", "pending")
        for name in _REQUIRED_FOR_TRAFFIC
    )

    return ready, {
        "status": "ready" if ready else "not_ready",
        "version": APP_VERSION,
        "git_sha": settings.git_sha,
        "environment": settings.app_env,
        "dependencies": dependencies,
    }


def log_startup_diagnostics() -> None:
    """One line at boot recording what this instance actually is.

    When two deploys behave differently, the first question is always
    which commit and which model configuration each one is running. This
    puts the answer in the logs without needing the endpoint to be
    reachable, which matters precisely when it isn't.
    """
    logger.info(
        "documind starting",
        extra={
            "version": APP_VERSION,
            "git_sha": settings.git_sha,
            "environment": settings.app_env,
            "embedding_model": settings.gemini_embedding_model,
            "generation_model": settings.gemini_llm_model,
            "reranker_model": settings.reranker_model,
            "confidence_threshold": settings.confidence_threshold,
            "gemini_api_key_configured": bool(settings.gemini_api_key),
            "google_oauth_configured": bool(settings.google_oauth_client_id),
            "demo_proxy_secret_configured": bool(settings.demo_proxy_shared_secret),
        },
    )
