import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from src.backend.core.config import settings
from src.backend.core.database import get_db
from src.backend.main import app
from src.backend.models.base import Base

# Ensure test DB safety guard
test_db_url = settings.TEST_DATABASE_URL
if "test" not in test_db_url.lower():
    raise RuntimeError(f"Unsafe TEST_DATABASE_URL '{test_db_url}'. Must contain 'test' to prevent data loss on production/development databases.")

test_engine = create_engine(test_db_url, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine, expire_on_commit=False)

# Rebind core database engine and SessionLocal to guarantee all test workers & live servers use test DB
import src.backend.core.database as core_db
core_db.engine = test_engine
core_db.SessionLocal = TestingSessionLocal

@pytest.fixture(scope="session", autouse=True)
def prepare_test_database():
    """Ensures test database tables exist."""
    Base.metadata.create_all(bind=test_engine)
    yield

@pytest.fixture
def db_session():
    """Yields a database session rollback-isolated or transaction-wrapped for tests."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()

@pytest.fixture
def client(db_session):
    """Yields a FastAPI TestClient with get_db overridden to use db_session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()
