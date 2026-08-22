"""Integration tests for API endpoints with real database.

These tests verify the complete flow from API endpoints through repositories
to the database and back.

Run with: pytest backend/tests/test_integration_api.py -v
"""

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _create_auth_headers(engine):
    """Create a test tenant/user and return auth headers."""
    from sqlalchemy.orm import sessionmaker
    from models.base import Tenant, User
    from utils.auth import create_access_token

    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    tenant_id = uuid4()
    user_id = uuid4()

    tenant = Tenant(tenant_id=tenant_id, name=f"tenant-{tenant_id}", is_active=1)
    user = User(
        user_id=user_id,
        email=f"user-{user_id}@example.com",
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
    return {"Authorization": f"Bearer {token}"}, tenant_id


@pytest.fixture
def client(test_engine, setup_database):  # noqa: ARG001
    """Test client using the test database engine."""
    from main import app
    import services.db.postgres_service as postgres_service
    from sqlalchemy.orm import sessionmaker

    original_engine = postgres_service.engine
    original_session_local = postgres_service.SessionLocal

    # Override the postgres_service engine with our test engine
    postgres_service.engine = test_engine
    postgres_service.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )

    with TestClient(app) as test_client:
        yield test_client

    postgres_service.engine = original_engine
    postgres_service.SessionLocal = original_session_local


@pytest.fixture
def auth_headers(test_engine, setup_database):  # noqa: ARG001
    """Auth headers - user created in same database as client uses."""
    headers, _ = _create_auth_headers(test_engine)
    return headers


@pytest.fixture
def other_auth_headers(test_engine, setup_database):  # noqa: ARG001
    """Different tenant auth headers - user created in same database as client uses."""
    headers, _ = _create_auth_headers(test_engine)
    return headers


class TestIngestDocumentIntegration:
    """Test document ingestion with real database persistence."""

    def test_ingest_creates_document_in_database(
        self, client, auth_headers, setup_database
    ):
        """Test that POST /ingest actually persists document to database."""
        # Create a test file
        file_content = b"Test PDF content for integration test"
        files = {
            "file": ("test_integration.pdf", BytesIO(file_content), "application/pdf")
        }
        data = {"doc_name": "Integration Test Doc", "doc_type": "report"}

        # Ingest document
        response = client.post("/ingest", files=files, data=data, headers=auth_headers)

        assert response.status_code == 201
        doc_data = response.json()

        # Verify response structure
        assert "doc_id" in doc_data
        assert doc_data["doc_name"] == "Integration Test Doc"
        assert doc_data["doc_type"] == "report"
        assert doc_data["status"] == "queued"
        assert doc_data["pages"] == 0  # Not processed yet

        # Retrieve the same document to verify persistence
        doc_id = doc_data["doc_id"]
        get_response = client.get(f"/documents/{doc_id}", headers=auth_headers)

        assert get_response.status_code == 200
        retrieved_doc = get_response.json()
        assert retrieved_doc["doc_id"] == doc_id
        assert retrieved_doc["doc_name"] == "Integration Test Doc"

    def test_ingest_deduplicates_by_sha256(self, client, auth_headers, setup_database):
        """Test that ingesting same file twice returns same document."""
        file_content = b"Duplicate test content"
        files1 = {"file": ("duplicate1.pdf", BytesIO(file_content), "application/pdf")}
        files2 = {"file": ("duplicate2.pdf", BytesIO(file_content), "application/pdf")}

        # Ingest first time
        response1 = client.post("/ingest", files=files1, headers=auth_headers)
        assert response1.status_code == 201
        doc1_id = response1.json()["doc_id"]
        doc1_sha256 = response1.json()["sha256"]

        # Ingest second time (same content, different filename)
        response2 = client.post("/ingest", files=files2, headers=auth_headers)
        assert response2.status_code == 201
        doc2_id = response2.json()["doc_id"]
        doc2_sha256 = response2.json()["sha256"]

        # Should be the same document (deduplication)
        assert doc1_id == doc2_id
        assert doc1_sha256 == doc2_sha256


class TestGetDocumentIntegration:
    """Test document retrieval with tenant isolation."""

    def test_get_document_returns_persisted_data(
        self, client, auth_headers, setup_database
    ):
        """Test that GET /documents/{doc_id} retrieves real data."""
        # First, create a document
        file_content = b"Retrieval test content"
        files = {"file": ("retrieval.pdf", BytesIO(file_content), "application/pdf")}
        data = {"doc_name": "Retrieval Test Doc"}

        ingest_response = client.post(
            "/ingest", files=files, data=data, headers=auth_headers
        )
        doc_id = ingest_response.json()["doc_id"]

        # Now retrieve it
        get_response = client.get(f"/documents/{doc_id}", headers=auth_headers)

        assert get_response.status_code == 200
        doc = get_response.json()
        assert doc["doc_id"] == doc_id
        assert doc["doc_name"] == "Retrieval Test Doc"

    def test_get_document_enforces_tenant_isolation(
        self, client, auth_headers, other_auth_headers, setup_database
    ):
        """Test that document is not accessible by different tenant."""
        # Create document with tenant 1
        file_content = b"Tenant isolation test"
        files = {"file": ("tenant.pdf", BytesIO(file_content), "application/pdf")}

        ingest_response = client.post("/ingest", files=files, headers=auth_headers)
        doc_id = ingest_response.json()["doc_id"]

        # Try to retrieve with tenant 2
        get_response = client.get(f"/documents/{doc_id}", headers=other_auth_headers)

        # Should return 404 (not found for this tenant)
        assert get_response.status_code == 404

    def test_get_nonexistent_document_returns_404(
        self, client, auth_headers, setup_database
    ):
        """Test that requesting non-existent document returns 404."""
        fake_doc_id = str(uuid4())

        response = client.get(f"/documents/{fake_doc_id}", headers=auth_headers)

        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/problem+json")


class TestQueryIntegration:
    """Test query endpoint with trace recording."""

    def test_query_records_trace(self, client, auth_headers, setup_database):
        """Test that POST /query creates a trace in database."""
        payload = {"q": "test query for integration", "k": 5}

        # Execute query
        response = client.post("/query", json=payload, headers=auth_headers)

        assert response.status_code == 200
        query_data = response.json()

        # Verify response structure
        assert "query_id" in query_data
        assert "trace_id" in query_data
        assert "answers" in query_data
        assert len(query_data["answers"]) > 0

        # Retrieve the trace to verify persistence
        trace_id = query_data["trace_id"]
        trace_response = client.get(f"/traces/{trace_id}", headers=auth_headers)

        assert trace_response.status_code == 200
        trace = trace_response.json()
        assert trace["trace_id"] == trace_id
        assert trace["query_id"] == query_data["query_id"]
        assert len(trace["steps"]) > 0
        assert len(trace["tools_used"]) > 0


class TestGetTraceIntegration:
    """Test trace retrieval with tenant isolation."""

    def test_get_trace_returns_persisted_data(
        self, client, auth_headers, setup_database
    ):
        """Test that GET /traces/{trace_id} retrieves real data."""
        # First, create a trace via query
        payload = {"q": "trace retrieval test", "k": 3}
        query_response = client.post("/query", json=payload, headers=auth_headers)
        trace_id = query_response.json()["trace_id"]

        # Now retrieve it
        trace_response = client.get(f"/traces/{trace_id}", headers=auth_headers)

        assert trace_response.status_code == 200
        trace = trace_response.json()
        assert trace["trace_id"] == trace_id
        assert "steps" in trace
        assert "tools_used" in trace
        assert "citations" in trace

    def test_get_trace_enforces_tenant_isolation(
        self, client, auth_headers, other_auth_headers, setup_database
    ):
        """Test that trace is not accessible by different tenant."""
        # Create trace with tenant 1
        payload = {"q": "tenant trace test", "k": 3}
        query_response = client.post("/query", json=payload, headers=auth_headers)
        trace_id = query_response.json()["trace_id"]

        # Try to retrieve with tenant 2
        trace_response = client.get(f"/traces/{trace_id}", headers=other_auth_headers)

        # Should return 404 (not found for this tenant)
        assert trace_response.status_code == 404


class TestEndToEndFlow:
    """Test complete end-to-end flow: ingest → query → trace."""

    def test_complete_flow(self, client, auth_headers, setup_database):
        """Test full workflow from ingestion to query to trace retrieval."""
        # Step 1: Ingest a document
        file_content = b"End-to-end test content with some sample text"
        files = {"file": ("e2e.pdf", BytesIO(file_content), "application/pdf")}
        data = {"doc_name": "E2E Test Doc", "doc_type": "report"}

        ingest_response = client.post(
            "/ingest", files=files, data=data, headers=auth_headers
        )
        assert ingest_response.status_code == 201
        doc_id = ingest_response.json()["doc_id"]

        # Step 2: Retrieve the document
        get_doc_response = client.get(f"/documents/{doc_id}", headers=auth_headers)
        assert get_doc_response.status_code == 200
        assert get_doc_response.json()["doc_name"] == "E2E Test Doc"

        # Step 3: Execute a query
        query_payload = {"q": "sample text", "k": 5}
        query_response = client.post("/query", json=query_payload, headers=auth_headers)
        assert query_response.status_code == 200
        trace_id = query_response.json()["trace_id"]

        # Step 4: Retrieve the trace
        trace_response = client.get(f"/traces/{trace_id}", headers=auth_headers)
        assert trace_response.status_code == 200
        trace = trace_response.json()

        # Verify trace has expected structure
        assert len(trace["steps"]) >= 2  # At least query_received and chunk_retrieval
        assert "document_repository" in trace["tools_used"]
        assert "chunk_repository" in trace["tools_used"]

        print("\n✅ Complete E2E flow successful:")
        print(f"   1. Ingested document: {doc_id}")
        print(f"   2. Retrieved document: {doc_id}")
        print(f"   3. Executed query with {len(trace['steps'])} steps")
        print(f"   4. Retrieved trace: {trace_id}")
