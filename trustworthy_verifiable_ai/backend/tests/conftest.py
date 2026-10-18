"""Test configuration and fixtures with isolated in-memory database."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.security import create_access_token
from app.db.base import Base
from app.db.seed import seed_database
from app.db.session import get_db
from app.main import app

# In-memory test SQLite engine
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(test_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create all tables in test database once for the session."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    """Yield an isolated transaction-bound session for each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # Seed fresh data into this session
    seed_database(session)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    """FastAPI TestClient with overridden get_db dependency."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def token_customer_a():
    """Valid JWT token for Customer A."""
    return create_access_token(subject="USR-CUST-A", role="customer")


@pytest.fixture
def token_customer_b():
    """Valid JWT token for Customer B."""
    return create_access_token(subject="USR-CUST-B", role="customer")


@pytest.fixture
def token_agent():
    """Valid JWT token for Support Agent."""
    return create_access_token(subject="USR-AGENT-1", role="agent")


@pytest.fixture
def token_reviewer():
    """Valid JWT token for Reviewer."""
    return create_access_token(subject="USR-REV-1", role="reviewer")
