"""Test database setup - models and session management.

Run with: pytest backend/tests/test_database_setup.py -v
"""

import uuid

import pytest
from models.base import (
    Chunk,
    Document,
    Entity,
    EntityMention,
    Relation,
    Trace,
)
from sqlalchemy import inspect


class TestDatabaseSchema:
    """Test that all tables and columns are created correctly."""

    def test_all_tables_exist(self, setup_database, test_engine):
        """Verify all 8 tables are created."""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()

        expected_tables = [
            "documents",
            "chunks",
            "entities",
            "entity_mentions",
            "relations",
            "evidence",
            "relation_evidence",
            "traces",
        ]

        for table in expected_tables:
            assert table in tables, f"Table {table} not found"

    def test_document_table_columns(self, setup_database, test_engine):
        """Verify Document table has all required columns."""
        inspector = inspect(test_engine)
        columns = {col["name"] for col in inspector.get_columns("documents")}

        required_columns = {
            "doc_id",
            "sha256",
            "mime",
            "pages",
            "source_uri",
            "doc_name",
            "ingest_run_id",
            "doc_type",
            "status",
            "version",
            "embedding_id",
            "tenant_id",
            "created_at",
        }

        assert required_columns.issubset(columns), (
            f"Missing columns: {required_columns - columns}"
        )

    def test_chunk_table_columns(self, setup_database, test_engine):
        """Verify Chunk table has all required columns."""
        inspector = inspect(test_engine)
        columns = {col["name"] for col in inspector.get_columns("chunks")}

        required_columns = {
            "chunk_id",
            "doc_id",
            "text",
            "checksum",
            "page",
            "section",
            "span",
            "layout",
            "overlap",
            "vector_id",
            "embedding_id",
            "chunk_metadata",
        }

        assert required_columns.issubset(columns), (
            f"Missing columns: {required_columns - columns}"
        )

    def test_entity_table_columns(self, setup_database, test_engine):
        """Verify Entity table has all required columns."""
        inspector = inspect(test_engine)
        columns = {col["name"] for col in inspector.get_columns("entities")}

        required_columns = {
            "entity_id",
            "name",
            "type",
            "aliases",
            "canonical",
            "tenant_id",
            "created_at",
        }

        assert required_columns.issubset(columns), (
            f"Missing columns: {required_columns - columns}"
        )

    def test_trace_table_columns(self, setup_database, test_engine):
        """Verify Trace table has all required columns."""
        inspector = inspect(test_engine)
        columns = {col["name"] for col in inspector.get_columns("traces")}

        required_columns = {
            "trace_id",
            "query_id",
            "steps",
            "tools_used",
            "citations",
            "agent_plan",
            "version",
            "tenant_id",
            "created_at",
        }

        assert required_columns.issubset(columns), (
            f"Missing columns: {required_columns - columns}"
        )


class TestDocumentModel:
    """Test Document model CRUD operations."""

    def test_create_document(self, db_session):
        """Test creating a document with all required fields."""
        tenant_id = uuid.uuid4()
        doc = Document(
            sha256="a" * 64,
            mime="application/pdf",
            pages=42,
            source_uri="s3://test/doc.pdf",
            doc_name="Test Document",
            ingest_run_id=uuid.uuid4(),
            doc_type="report",
            status="queued",
            version=1,
            embedding_id="nomic-embed-text-v1.5",
            tenant_id=tenant_id,
        )

        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        assert doc.doc_id is not None
        assert doc.sha256 == "a" * 64
        assert doc.pages == 42
        assert doc.status == "queued"
        assert doc.tenant_id == tenant_id
        assert doc.created_at is not None

    def test_document_unique_sha256(self, db_session):
        """Test that SHA256 uniqueness is enforced."""
        tenant_id = uuid.uuid4()

        doc1 = Document(
            sha256="unique123",
            mime="application/pdf",
            pages=10,
            source_uri="test1.pdf",
            doc_name="Doc 1",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            status="queued",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.add(doc1)
        db_session.commit()

        # Try to create another document with same SHA256
        doc2 = Document(
            sha256="unique123",
            mime="application/pdf",
            pages=20,
            source_uri="test2.pdf",
            doc_name="Doc 2",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            status="queued",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.add(doc2)

        with pytest.raises(Exception):  # Unique constraint violation
            db_session.commit()

    def test_query_document_by_tenant(self, db_session):
        """Test querying documents filtered by tenant_id."""
        tenant1 = uuid.uuid4()
        tenant2 = uuid.uuid4()

        # Create docs for two tenants
        for i in range(3):
            doc = Document(
                sha256=f"tenant1_{i}",
                mime="application/pdf",
                pages=10,
                source_uri=f"test{i}.pdf",
                doc_name=f"Doc {i}",
                ingest_run_id=uuid.uuid4(),
                doc_type="pdf",
                status="queued",
                tenant_id=tenant1,
                embedding_id="test",
            )
            db_session.add(doc)

        for i in range(2):
            doc = Document(
                sha256=f"tenant2_{i}",
                mime="application/pdf",
                pages=10,
                source_uri=f"test{i}.pdf",
                doc_name=f"Doc {i}",
                ingest_run_id=uuid.uuid4(),
                doc_type="pdf",
                status="queued",
                tenant_id=tenant2,
                embedding_id="test",
            )
            db_session.add(doc)

        db_session.commit()

        # Query tenant1 docs
        tenant1_docs = (
            db_session.query(Document).filter(Document.tenant_id == tenant1).all()
        )
        assert len(tenant1_docs) == 3

        # Query tenant2 docs
        tenant2_docs = (
            db_session.query(Document).filter(Document.tenant_id == tenant2).all()
        )
        assert len(tenant2_docs) == 2


class TestChunkModel:
    """Test Chunk model and relationships."""

    def test_create_chunk_with_document(self, db_session):
        """Test creating chunks linked to a document."""
        tenant_id = uuid.uuid4()

        # Create document
        doc = Document(
            sha256="doc123",
            mime="application/pdf",
            pages=10,
            source_uri="test.pdf",
            doc_name="Test Doc",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            status="queued",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.add(doc)
        db_session.commit()

        # Create chunk
        chunk = Chunk(
            doc_id=doc.doc_id,
            text="This is a test chunk of text.",
            checksum="abc123",
            page=1,
            section="Introduction",
            span={"start": 0, "end": 29},
            layout={"bbox": [10, 20, 100, 50], "block_type": "paragraph"},
            overlap=0.25,
            vector_id="qdrant_point_123",
            embedding_id="nomic-embed-text-v1.5",
            chunk_metadata={"language": "en", "confidence": 0.95},
        )
        db_session.add(chunk)
        db_session.commit()
        db_session.refresh(chunk)

        assert chunk.chunk_id is not None
        assert chunk.doc_id == doc.doc_id
        assert chunk.page == 1
        assert chunk.span["start"] == 0
        assert chunk.layout["block_type"] == "paragraph"

    def test_chunk_cascade_delete(self, db_session):
        """Test that deleting document cascades to chunks."""
        tenant_id = uuid.uuid4()

        # Create document with chunks
        doc = Document(
            sha256="cascade_test",
            mime="application/pdf",
            pages=1,
            source_uri="test.pdf",
            doc_name="Test Doc",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            status="queued",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.add(doc)
        db_session.commit()

        # Add chunks
        for i in range(3):
            chunk = Chunk(
                doc_id=doc.doc_id,
                text=f"Chunk {i}",
                checksum=f"check{i}",
                page=1,
                span={"start": i * 10, "end": (i + 1) * 10},
                embedding_id="test",
            )
            db_session.add(chunk)
        db_session.commit()

        doc_id = doc.doc_id

        # Verify chunks exist
        chunks_before = db_session.query(Chunk).filter(Chunk.doc_id == doc_id).count()
        assert chunks_before == 3

        # Delete document
        db_session.delete(doc)
        db_session.commit()

        # Verify chunks are deleted
        chunks_after = db_session.query(Chunk).filter(Chunk.doc_id == doc_id).count()
        assert chunks_after == 0


class TestEntityGraphModels:
    """Test Entity, EntityMention, Relation, Evidence models."""

    def test_create_entity_with_mentions(self, db_session):
        """Test creating entities with mentions."""
        tenant_id = uuid.uuid4()

        # Create document and chunk
        doc = Document(
            sha256="entity_test",
            mime="application/pdf",
            pages=1,
            source_uri="test.pdf",
            doc_name="Test Doc",
            ingest_run_id=uuid.uuid4(),
            doc_type="pdf",
            status="queued",
            tenant_id=tenant_id,
            embedding_id="test",
        )
        db_session.add(doc)
        db_session.commit()

        chunk = Chunk(
            doc_id=doc.doc_id,
            text="Acetaminophen inhibits COX-2.",
            checksum="test",
            page=1,
            span={"start": 0, "end": 29},
            embedding_id="test",
        )
        db_session.add(chunk)
        db_session.commit()

        # Create entity
        entity = Entity(
            entity_id="ent:123",
            name="Acetaminophen",
            type="Chemical",
            aliases=["APAP", "Paracetamol"],
            tenant_id=tenant_id,
        )
        db_session.add(entity)
        db_session.commit()

        # Create mention
        mention = EntityMention(
            mention_id="men:456",
            entity_id=entity.entity_id,
            doc_id=doc.doc_id,
            chunk_id=chunk.chunk_id,
            page=1,
            span={"start": 0, "end": 13},
            surface="Acetaminophen",
            confidence=0.95,
        )
        db_session.add(mention)
        db_session.commit()

        # Verify relationships
        assert len(entity.mentions) == 1
        assert entity.mentions[0].surface == "Acetaminophen"

    def test_create_relation_with_evidence(self, db_session):
        """Test creating relations with evidence."""
        tenant_id = uuid.uuid4()

        # Create entities
        entity1 = Entity(
            entity_id="ent:drug1",
            name="Aspirin",
            type="Chemical",
            tenant_id=tenant_id,
        )
        entity2 = Entity(
            entity_id="ent:enzyme1", name="COX-2", type="Enzyme", tenant_id=tenant_id
        )
        db_session.add_all([entity1, entity2])
        db_session.commit()

        # Create relation
        relation = Relation(
            relation_id="rel:001",
            from_entity_id=entity1.entity_id,
            to_entity_id=entity2.entity_id,
            type="INHIBITS",
            weight=0.85,
        )
        db_session.add(relation)
        db_session.commit()

        # Verify relation
        assert relation.from_entity.name == "Aspirin"
        assert relation.to_entity.name == "COX-2"
        assert relation.type == "INHIBITS"


class TestTraceModel:
    """Test Trace model for observability."""

    def test_create_trace(self, db_session):
        """Test creating a trace with all fields."""
        tenant_id = uuid.uuid4()
        query_id = uuid.uuid4()

        trace = Trace(
            query_id=query_id,
            steps=[
                {"t": "2025-10-19T12:00:00Z", "step": "dense_search", "lat_ms": 45},
                {"t": "2025-10-19T12:00:01Z", "step": "rerank", "lat_ms": 120},
            ],
            tools_used=["search_qdrant", "rerank"],
            citations=[{"sentence_ix": 0, "chunk_id": str(uuid.uuid4()), "page": 1}],
            agent_plan={"variant": "ReAct", "swarm": False},
            tenant_id=tenant_id,
        )

        db_session.add(trace)
        db_session.commit()
        db_session.refresh(trace)

        assert trace.trace_id is not None
        assert trace.query_id == query_id
        assert len(trace.steps) == 2
        assert trace.tools_used == ["search_qdrant", "rerank"]
        assert trace.version == 1
