"""Test configuration - mocks heavy ML dependencies."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend directory to Python path for imports
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set test environment
os.environ["APP_ENV"] = "test"

# Set required environment variables for tests
test_env_vars = {
    "APP_NAME": "omnirag-test",
    "POSTGRES_USER": "test",
    "POSTGRES_PASSWORD": "test",
    "POSTGRES_DB": "test",
    "POSTGRES_URL": "sqlite:///:memory:",  # Use SQLite by default for tests
    "JWT_SECRET_KEY": "test-jwt-secret",
    "NEO_USER": "test",
    "NEO_PASSWORD": "test",
    "NEO_DB": "test",
    "NEO_URI": "bolt://localhost:7687",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672/",
    "SHAREPOINT_TENANT_ID": "test-tenant-id",
    "SHAREPOINT_CLIENT_ID": "test-client-id",
    "SHAREPOINT_CLIENT_SECRET": "test-client-secret",
    "SHAREPOINT_SITE_ID": "test-site-id",
    "QDRANT_HOST": "localhost",
    "QDRANT_PORT": "6333",
    "QDRANT_URI": "http://localhost:6333",
    "BLOB_STORAGE_DIR": "data/blob_storage",
    "DOCUMENTS_DIR": "data/documents",
}

# Set environment variables only if not already set
for key, value in test_env_vars.items():
    if key not in os.environ:
        os.environ[key] = value

# Mock ML client to avoid importing httpx and ML dependencies
mock_ml_client = MagicMock()
mock_ml_client.base_url = "http://mock-ml-service:8000"
mock_ml_client.generate_embeddings = MagicMock(return_value=[[0.1] * 1024])
mock_ml_client.generate_embeddings_async = MagicMock(return_value=[[0.1] * 1024])
mock_ml_client.rerank_candidates = MagicMock(return_value=[])
mock_ml_client.rerank_candidates_async = MagicMock(return_value=[])

sys.modules["services.ml_client"] = MagicMock(
    MLServiceClient=MagicMock, ml_client=mock_ml_client
)

# Mock heavy ML libraries before any imports
sys.modules["paddleocr"] = MagicMock()
sys.modules["paddlepaddle"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchvision"] = MagicMock()
sys.modules["transformers"] = MagicMock()
sys.modules["sentence_transformers"] = MagicMock()
sys.modules["docling"] = MagicMock()
sys.modules["docling_core"] = MagicMock()
sys.modules["docling_parse"] = MagicMock()
sys.modules["layoutparser"] = MagicMock()

# Mock task queue dependencies (not tested in CI)
sys.modules["celery"] = MagicMock()
sys.modules["pika"] = MagicMock()
sys.modules["redis"] = MagicMock()


@pytest.fixture(scope="function")
def test_engine():
    """Create a test database engine for each test."""
    # Import here to ensure mocks are in place
    from config.settings import settings
    from sqlalchemy.pool import StaticPool

    # Use SQLite for tests unless POSTGRES_URL explicitly set
    if "sqlite" in settings.postgres_url:
        # For SQLite, create a new in-memory database for each test
        # Use StaticPool to ensure all connections share the same in-memory database
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,  # Critical: ensures same connection is reused
        )

        # Enable foreign key constraints for SQLite
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):  # noqa: ARG001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        engine = create_engine(settings.postgres_url)

    return engine


@pytest.fixture(scope="function")
def setup_database(test_engine):
    """Create all tables for each test."""
    # Import here to ensure proper initialization order
    from models.base import Base

    # Create all tables
    Base.metadata.create_all(bind=test_engine)
    yield
    # Drop all tables after tests
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session(setup_database, test_engine):  # noqa: ARG001
    """Provide a transactional database session for tests."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = SessionLocal()

    # Begin a transaction
    connection = test_engine.connect()
    transaction = connection.begin()
    session.bind = connection

    yield session

    # Rollback the transaction
    session.close()
    transaction.rollback()
    connection.close()
