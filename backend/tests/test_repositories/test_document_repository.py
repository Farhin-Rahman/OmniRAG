"""Tests for DocumentRepository.

Run with: pytest backend/tests/test_repositories/test_document_repository.py -v
"""

import uuid

import pytest
from repositories.document_repository import DocumentRepository


class TestDocumentRepositoryCreate:
    """Test document creation."""

    def test_create_document_success(self, db_session):
        """Test creating a document with all fields."""
        tenant_id = uuid.uuid4()
        ingest_run_id = uuid.uuid4()

        doc = DocumentRepository.create(
            session=db_session,
            sha256="a" * 64,
            mime="application/pdf",
            pages=42,
            source_uri="s3://test/doc.pdf",
            doc_name="Test Document",
            ingest_run_id=ingest_run_id,
            doc_type="report",
            tenant_id=tenant_id,
            embedding_id="nomic-embed-text-v1.5",
        )

        assert doc.doc_id is not None
        assert doc.sha256 == "a" * 64
        assert doc.pages == 42
        assert doc.status == "queued"
        assert doc.tenant_id == tenant_id
        assert doc.created_at is not None

    def test_create_duplicate_sha256_fails(self, db_session):
        """Test that creating document with duplicate SHA256 fails."""
        tenant_id = uuid.uuid4()
        sha256 = "duplicate123" + ("0" * 52)

        # Create first document
        DocumentRepository.create(
            session=db_session,
            sha256=sha256,
            mime="application/pdf",
            pages=10,
            source_uri="test1.pdf",
            doc_name="Doc 1",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.commit()

        # Try to create second document with same SHA256
        with pytest.raises(Exception):  # IntegrityError
            DocumentRepository.create(
                session=db_session,
                sha256=sha256,
                mime="application/pdf",
                pages=20,
                source_uri="test2.pdf",
                doc_name="Doc 2",
                ingest_run_id=uuid.uuid4(),
                doc_type="pdf",
                tenant_id=tenant_id,
                embedding_id="test",
            )
            db_session.commit()


class TestDocumentRepositoryRead:
    """Test document retrieval operations."""

    def test_get_by_id_success(self, db_session):
        """Test retrieving document by ID."""
        tenant_id = uuid.uuid4()

        # Create document
        doc = DocumentRepository.create(
            session=db_session,
            sha256="get_by_id_test" + ("0" * 48),
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Test Doc",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.commit()

        # Retrieve document
        found = DocumentRepository.get_by_id(db_session, doc.doc_id, tenant_id)

        assert found is not None
        assert found.doc_id == doc.doc_id
        assert found.doc_name == "Test Doc"

    def test_get_by_id_wrong_tenant_returns_none(self, db_session):
        """Test that document is not accessible by different tenant."""
        tenant1 = uuid.uuid4()
        tenant2 = uuid.uuid4()

        # Create document for tenant1
        doc = DocumentRepository.create(
            session=db_session,
            sha256="tenant_isolation_test" + ("0" * 41),
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Tenant 1 Doc",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant1,
            embedding_id="test",
        )
        db_session.commit()

        # Try to retrieve with tenant2
        found = DocumentRepository.get_by_id(db_session, doc.doc_id, tenant2)

        assert found is None

    def test_get_by_sha256_success(self, db_session):
        """Test retrieving document by SHA256."""
        tenant_id = uuid.uuid4()
        sha256 = "sha256_test" + ("0" * 53)

        # Create document
        DocumentRepository.create(
            session=db_session,
            sha256=sha256,
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="SHA256 Test",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.commit()

        # Retrieve by SHA256
        found = DocumentRepository.get_by_sha256(db_session, sha256, tenant_id)

        assert found is not None
        assert found.sha256 == sha256
        assert found.doc_name == "SHA256 Test"

    def test_list_by_tenant(self, db_session):
        """Test listing documents for a tenant."""
        tenant1 = uuid.uuid4()
        tenant2 = uuid.uuid4()

        # Create docs for tenant1
        for i in range(3):
            DocumentRepository.create(
                session=db_session,
                sha256=f"tenant1_{i}" + ("0" * 53),
                mime="application/pdf",
                pages=10,
                source_uri=f"test{i}.pdf",
                doc_name=f"Doc {i}",
                ingest_run_id=uuid.uuid4(),
                doc_type="pdf",
                tenant_id=tenant1,
                embedding_id="test",
            )

        # Create docs for tenant2
        for i in range(2):
            DocumentRepository.create(
                session=db_session,
                sha256=f"tenant2_{i}" + ("0" * 53),
                mime="application/pdf",
                pages=10,
                source_uri=f"test{i}.pdf",
                doc_name=f"Doc {i}",
                ingest_run_id=uuid.uuid4(),
                doc_type="pdf",
                tenant_id=tenant2,
                embedding_id="test",
            )
        db_session.commit()

        # List tenant1 docs
        tenant1_docs = DocumentRepository.list_by_tenant(db_session, tenant1)
        assert len(tenant1_docs) == 3

        # List tenant2 docs
        tenant2_docs = DocumentRepository.list_by_tenant(db_session, tenant2)
        assert len(tenant2_docs) == 2

    def test_count_by_tenant(self, db_session):
        """Test counting documents for a tenant."""
        tenant_id = uuid.uuid4()

        # Create multiple documents
        for i in range(5):
            DocumentRepository.create(
                session=db_session,
                sha256=f"count_test_{i}" + ("0" * 50),
                mime="application/pdf",
                pages=10,
                source_uri=f"test{i}.pdf",
                doc_name=f"Doc {i}",
                ingest_run_id=uuid.uuid4(),
                doc_type="pdf" if i % 2 == 0 else "report",
                tenant_id=tenant_id,
                embedding_id="test",
                status="ready" if i < 3 else "queued",
            )
        db_session.commit()

        # Count all
        total = DocumentRepository.count_by_tenant(db_session, tenant_id)
        assert total == 5

        # Count by status
        ready_count = DocumentRepository.count_by_tenant(
            db_session, tenant_id, status="ready"
        )
        assert ready_count == 3

        # Count by type
        pdf_count = DocumentRepository.count_by_tenant(
            db_session, tenant_id, doc_type="pdf"
        )
        assert pdf_count == 3


class TestDocumentRepositoryUpdate:
    """Test document update operations."""

    def test_update_status_success(self, db_session):
        """Test updating document status."""
        tenant_id = uuid.uuid4()

        # Create document with queued status
        doc = DocumentRepository.create(
            session=db_session,
            sha256="status_update_test" + ("0" * 46),
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Status Test",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.commit()

        assert doc.status == "queued"

        # Update status
        updated = DocumentRepository.update_status(
            db_session, doc.doc_id, "processing", tenant_id
        )
        db_session.commit()

        assert updated is not None
        assert updated.status == "processing"

    def test_update_status_wrong_tenant_returns_none(self, db_session):
        """Test that status update fails for wrong tenant."""
        tenant1 = uuid.uuid4()
        tenant2 = uuid.uuid4()

        # Create document for tenant1
        doc = DocumentRepository.create(
            session=db_session,
            sha256="status_tenant_test" + ("0" * 46),
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Tenant Test",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant1,
            embedding_id="test",
        )
        db_session.commit()

        # Try to update with tenant2
        updated = DocumentRepository.update_status(
            db_session, doc.doc_id, "ready", tenant2
        )

        assert updated is None


class TestDocumentRepositoryDelete:
    """Test document deletion operations."""

    def test_delete_success(self, db_session):
        """Test deleting a document."""
        tenant_id = uuid.uuid4()

        # Create document
        doc = DocumentRepository.create(
            session=db_session,
            sha256="delete_test" + ("0" * 52),
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Delete Test",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.commit()

        doc_id = doc.doc_id

        # Delete document
        deleted = DocumentRepository.delete(db_session, doc_id, tenant_id)
        db_session.commit()

        assert deleted is True

        # Verify document is gone
        found = DocumentRepository.get_by_id(db_session, doc_id, tenant_id)
        assert found is None

    def test_delete_wrong_tenant_returns_false(self, db_session):
        """Test that delete fails for wrong tenant."""
        tenant1 = uuid.uuid4()
        tenant2 = uuid.uuid4()

        # Create document for tenant1
        doc = DocumentRepository.create(
            session=db_session,
            sha256="delete_tenant_test" + ("0" * 45),
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Tenant Test",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            tenant_id=tenant1,
            embedding_id="test",
        )
        db_session.commit()

        # Try to delete with tenant2
        deleted = DocumentRepository.delete(db_session, doc.doc_id, tenant2)

        assert deleted is False

        # Verify document still exists
        found = DocumentRepository.get_by_id(db_session, doc.doc_id, tenant1)
        assert found is not None
