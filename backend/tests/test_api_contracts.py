from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import these before app to ensure proper initialization
from models.base import Base
from config.settings import settings


@pytest.fixture(scope="module")
def test_db():
    """Create a test database for the entire test module."""
    # Create test engine
    if "sqlite" in settings.postgres_url:
        test_engine = create_engine(
            "sqlite:///test_api_contracts.db",  # Use a file so it persists across tests
            connect_args={"check_same_thread": False},
        )
    else:
        test_engine = create_engine(settings.postgres_url)

    # Create all tables
    Base.metadata.create_all(bind=test_engine)

    # Override the engine in postgres_service
    import services.db.postgres_service

    original_engine = services.db.postgres_service.engine
    services.db.postgres_service.engine = test_engine

    # Update SessionLocal to use test engine
    services.db.postgres_service.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    yield test_engine

    # Restore original engine
    services.db.postgres_service.engine = original_engine

    # Clean up
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()

    # Remove test database file if using SQLite
    if "sqlite" in settings.postgres_url:
        import os

        try:
            os.remove("test_api_contracts.db")
        except OSError:
            pass


@pytest.fixture
def client(test_db):  # noqa: ARG001
    """Test client with database setup"""
    # Import app after database setup to ensure correct engine is used
    from main import app

    return TestClient(app)


@pytest.fixture
def auth_headers(test_db):
    """Auth headers with a valid JWT and seeded user."""
    from sqlalchemy.orm import sessionmaker
    from models.base import Tenant, User
    from utils.auth import create_access_token

    session = sessionmaker(autocommit=False, autoflush=False, bind=test_db)()
    tenant_id = uuid4()
    user_id = uuid4()

    # Use unique tenant name to avoid UNIQUE constraint failures
    tenant = Tenant(tenant_id=tenant_id, name=f"test-tenant-{tenant_id}", is_active=1)
    user = User(
        user_id=user_id,
        email=f"test-{user_id}@example.com",  # Use unique email to avoid constraint failures
        password_hash="test-hash",
        is_active=1,
        email_verified=1,
        role="member",
        tenant_id=tenant_id,
    )
    session.add(tenant)
    session.add(user)
    session.commit()

    # Capture attributes BEFORE closing session to avoid DetachedInstanceError
    user_email = user.email
    user_role = user.role
    session.close()

    token, _ = create_access_token(user_id, user_email, user_role, tenant_id)
    return {"Authorization": f"Bearer {token}"}


class TestHealthEndpoint:
    def test_healthz_success(self, client):
        """Test /healthz returns 200 with correct schema"""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "git_sha" in data
        assert data["status"] == "ok"

    def test_healthz_no_auth_required(self, client):
        """Test /healthz works without authentication"""
        response = client.get("/healthz")
        assert response.status_code == 200


class TestIngestEndpoint:
    def test_ingest_success(self, client, auth_headers):
        """Test /ingest returns 201 with Document"""
        file_content = b"test file content"
        files = {"file": ("test.pdf", BytesIO(file_content), "application/pdf")}

        response = client.post("/ingest", files=files, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()

        # Assert Document schema
        assert "doc_id" in data
        assert "sha256" in data
        assert "mime" in data
        assert "pages" in data
        assert "source_uri" in data
        assert "doc_name" in data
        assert "ingest_run_id" in data
        assert "doc_type" in data
        assert "status" in data
        assert "version" in data
        assert "created_at" in data
        assert "tenant_id" in data
        assert "embedding_id" in data

        # Assert status is queued
        assert data["status"] == "queued"

    def test_ingest_no_auth(self, client):
        """Test /ingest returns 401 without auth"""
        file_content = b"test file content"
        files = {"file": ("test.pdf", BytesIO(file_content), "application/pdf")}

        response = client.post("/ingest", files=files)
        assert response.status_code == 401


class TestDocumentEndpoint:
    def test_get_document_not_found(self, client, auth_headers):
        """Test /documents/{doc_id} returns 404 Problem JSON"""
        doc_id = str(uuid4())
        response = client.get(f"/documents/{doc_id}", headers=auth_headers)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")

        data = response.json()
        # Verify Problem JSON structure (RFC 7807-like with our extensions)
        assert "title" in data
        assert "status" in data
        assert data["status"] == 404
        assert "code" in data  # Our extension for error categorization
        assert "trace_id" in data  # Our extension for debugging


class TestQueryEndpoint:
    def test_query_success(self, client, auth_headers, monkeypatch):
        """Test /query returns 200 with QueryResponse"""

        # Mock the Qdrant search to return empty results
        def mock_search(self, *args, **kwargs):  # noqa: ARG001
            return []

        # Mock embedding service
        async def mock_generate_embedding(self, text):  # noqa: ARG001
            return [0.1] * 1024  # Return dummy embedding

        # Apply mocks
        monkeypatch.setattr(
            "services.db.qdrant_service.QdrantSearchService.search", mock_search
        )
        monkeypatch.setattr(
            "services.embedding_service.EmbeddingService.generate_embedding",
            mock_generate_embedding,
        )

        payload = {
            "q": "What are the main findings?",
            "k": 5,
            "require_citations": True,
        }

        response = client.post("/query", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Assert QueryResponse schema
        assert "query_id" in data
        assert "answers" in data
        assert "retrieval" in data
        assert "trace_id" in data

        # Assert answers structure
        assert len(data["answers"]) > 0
        answer = data["answers"][0]
        assert "text" in answer
        assert "citations" in answer
        assert "support" in answer
        assert "confidence" in answer


class TestTraceEndpoint:
    def test_get_trace_not_found(self, client, auth_headers):
        """Test /traces/{trace_id} returns 404 Problem JSON"""
        trace_id = str(uuid4())
        response = client.get(f"/traces/{trace_id}", headers=auth_headers)
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")

        data = response.json()
        assert "type" in data
        assert "title" in data
        assert "status" in data
        assert data["status"] == 404
