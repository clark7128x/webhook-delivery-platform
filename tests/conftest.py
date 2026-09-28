import os
os.environ["CELERY_ALWAYS_EAGER"] = "True"
os.environ["DATABASE_URL"] = "sqlite:///test.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from typing import Generator

from src.main import app
from src.database import get_db, Base, engine, SessionLocal
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_redis_client():
    mock = MagicMock()
    mock.incr.return_value = 1
    mock.ping.return_value = True
    with patch("src.rate_limit.redis_client", mock), patch("src.redis_client.redis_client", mock):
        yield mock


@pytest.fixture(scope="session", autouse=True)
def db_engine():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    if os.path.exists("test.db"):
        try:
            os.remove("test.db")
        except OSError:
            pass


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator:
    session = SessionLocal()
    yield session
    # Clean up all tables after each test to prevent leaks
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()
    session.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
