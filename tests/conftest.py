import os
from pathlib import Path

from dotenv import load_dotenv

env_test_path = Path(__file__).resolve().parent.parent / ".env.test"
load_dotenv(env_test_path, override=True)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.config import settings
from app.db.base import Base
import app.models
from app.main import app
import app.middleware.rate_limit as rate_limit_module

@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture(autouse=True)
def clean_slate(test_engine):
    # Runs before every test: wipe all rows, clear rate-limit memory.
    with test_engine.connect() as conn:
        trans = conn.begin()
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        trans.commit()

    rate_limit_module._request_counts.clear()
    yield

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c