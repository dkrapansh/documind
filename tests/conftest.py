import os
from pathlib import Path

from dotenv import load_dotenv

env_test_path = Path(__file__).resolve().parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import settings
from app.db.base import Base
import app.models
from app.main import app
import app.middleware.rate_limit as rate_limit_module
import app.api.routers.auth as auth_router_module

from sqlalchemy.orm import sessionmaker

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

def _alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config

@pytest.fixture(scope="session")
def test_engine():
    """Builds the schema by running the real `alembic upgrade head`, the
    same chain Dockerfile's CMD runs on every deploy - not
    Base.metadata.create_all, which only proves the current model
    definitions are internally consistent and would pass even if a
    migration were broken or missing (e.g. the pgvector Vector import
    gotcha CLAUDE.md warns about). A green test suite should mean the
    migration chain actually works, not just that today's models do.
    """
    command.upgrade(_alembic_config(), "head")
    engine = create_engine(settings.database_url)
    yield engine
    engine.dispose()
    command.downgrade(_alembic_config(), "base")

@pytest.fixture(autouse=True)
def clean_slate(test_engine):
    # Runs before every test: wipe all rows, clear rate-limit memory.
    with test_engine.connect() as conn:
        trans = conn.begin()
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        trans.commit()

    rate_limit_module._request_counts.clear()
    auth_router_module._demo_session_counts.clear()
    auth_router_module._create_key_counts.clear()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture
def db_session(test_engine):
    TestSessionLocal = sessionmaker(bind=test_engine)
    session = TestSessionLocal()
    yield session
    session.close()