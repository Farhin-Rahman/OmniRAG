"""SQLAlchemy ORM models for OmniRAG database schema.

Simplified for SQLite backend.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

from .db_types import JSONB, UUID

Base = declarative_base()


def utcnow():
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


class Document(Base):
    """Document metadata and ingestion tracking.

    Represents uploaded documents with deduplication via SHA256.
    Status tracks ingestion pipeline progress.
    """

    __tablename__ = "documents"

    # Primary key
    doc_id = Column(UUID(), primary_key=True, default=uuid.uuid4)

    # Content identification
    sha256 = Column(String(64), nullable=False, index=True)
    mime = Column(String(255), nullable=False)
    pages = Column(Integer, nullable=False, default=0)

    # Source metadata
    source_uri = Column(Text, nullable=False)
    doc_name = Column(String(512), nullable=False)
    doc_type = Column(String(64), nullable=False, index=True)

    # Ingestion tracking
    ingest_run_id = Column(UUID(), nullable=False, index=True)
    status = Column(
        String(20),  # "queued", "processing", "ready", "error"
        nullable=False,
        default="queued",
        index=True,
    )

    # Versioning and embedding
    version = Column(Integer, nullable=False, default=1)
    embedding_id = Column(String(64), nullable=False, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    # Relationships
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # No explicit Index("ix_documents_status", ...) here: the `status`
        # Column above already has index=True, which SQLAlchemy auto-names
        # ix_documents_status. Declaring both collided on create_all()
        # ("index ix_documents_status already exists").
        UniqueConstraint("sha256", name="uq_document_sha256"),
    )

    def __repr__(self):
        return f"<Document(doc_id={self.doc_id}, doc_name={self.doc_name}, status={self.status})>"


class Chunk(Base):
    """Text chunks from documents with layout and provenance.

    Chunks are indexed in Qdrant with vector_id linkage.
    Span represents byte/character offsets in source document.
    """

    __tablename__ = "chunks"

    # Primary key
    chunk_id = Column(UUID(), primary_key=True, default=uuid.uuid4)

    # Document reference
    doc_id = Column(
        UUID(),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Content
    text = Column(Text, nullable=False)
    checksum = Column(String(64), nullable=False)  # SHA1 of text for dedup

    # Position in document
    page = Column(Integer, nullable=False)
    section = Column(String(255), nullable=True)
    span = Column(JSONB, nullable=False)  # {"start": int, "end": int}

    # Layout metadata
    layout = Column(JSONB, nullable=True)  # {"bbox": [x0,y0,x1,y1], "block_type": str}
    overlap = Column(Float, nullable=False, default=0.0)

    # Vector indexing
    vector_id = Column(String(128), nullable=True, index=True)  # Qdrant point ID
    embedding_id = Column(String(64), nullable=False, index=True)

    # Additional metadata
    chunk_metadata = Column(JSONB, nullable=True)

    # Relationships
    document = relationship("Document", back_populates="chunks")

    __table_args__ = (Index("ix_chunks_doc_page", "doc_id", "page"),)

    def __repr__(self):
        return (
            f"<Chunk(chunk_id={self.chunk_id}, doc_id={self.doc_id}, page={self.page})>"
        )
