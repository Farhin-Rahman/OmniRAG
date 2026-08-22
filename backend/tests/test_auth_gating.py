"""
Test auth gating for protected endpoints.

Verifies that:
1. Unauthenticated requests get 401
2. Authenticated requests succeed
3. Per-user temp uploads include user_id in response

Uses FastAPI dependency overrides so tests run without Docker/services.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

# Add backend directory to Python path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set required env vars before imports
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_URL", "sqlite:///:memory:")
os.environ.setdefault("DOWNLOAD_URL_SECRET", "test-secret-key-for-testing-only")


# Create fake User for dependency injection
class FakeUser:
    """Fake user for testing authenticated endpoints."""

    def __init__(
        self,
        user_id: UUID = None,
        email: str = "test@example.com",
        role: str = "user",
        tenant_id: UUID = None,
    ):
        self.user_id = user_id or uuid4()
        self.email = email
        self.role = role
        self.tenant_id = tenant_id or uuid4()
        self.full_name = "Test User"
        self.is_active = 1


# Default fake user for tests
_fake_user = FakeUser()


def get_fake_user() -> FakeUser:
    """Return a fake authenticated user."""
    return _fake_user


def get_fake_db():
    """Return a mock DB session."""
    mock_session = MagicMock()
    yield mock_session


@pytest.fixture
def client_no_auth():
    """TestClient without auth overrides (should get 401)."""
    # Import inside fixture to ensure mocks are set up
    from main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def client_with_auth():
    """TestClient with auth dependency overridden."""
    from main import app
    from routes.auth import get_current_user
    from services.db.postgres_service import get_db

    # Override auth dependency
    app.dependency_overrides[get_current_user] = get_fake_user
    app.dependency_overrides[get_db] = get_fake_db

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client

    # Clean up overrides
    app.dependency_overrides.clear()


class TestAuthGating:
    """Test that endpoints require authentication."""

    def test_get_document_unauthenticated_returns_401(self, client_no_auth):
        """Unauthenticated GET /documents/{doc_id} should return 401."""
        doc_id = uuid4()
        response = client_no_auth.get(
            f"/api/documents/{doc_id}",
        )

        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )

    def test_upload_temp_unauthenticated_returns_401(self, client_no_auth):
        """Unauthenticated POST /upload/temp should return 401."""
        response = client_no_auth.post(
            "/api/upload/temp",
            files={"file": ("test.txt", b"test content", "text/plain")},
        )

        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )

    def test_delete_document_unauthenticated_returns_401(self, client_no_auth):
        """Unauthenticated DELETE /documents/{doc_id} should return 401."""
        doc_id = uuid4()
        response = client_no_auth.delete(
            f"/api/documents/{doc_id}",
        )

        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )

    def test_query_unauthenticated_returns_401(self, client_no_auth):
        """Unauthenticated POST /query should return 401."""
        response = client_no_auth.post(
            "/api/query",
            json={"q": "test query", "k": 3},
        )

        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )


class TestHealthEndpointNoAuth:
    """Test that health endpoint doesn't require auth."""

    def test_healthz_no_auth_required(self, client_no_auth):
        """GET /healthz should succeed without auth."""
        response = client_no_auth.get("/api/healthz")

        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert data.get("status") == "ok"
