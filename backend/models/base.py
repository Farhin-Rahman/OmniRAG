"""SQLAlchemy ORM models for OmniRAG database schema.

Simplified for SQLite backend.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base

from .db_types import UUID

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

    __table_args__ = (
        # No explicit Index("ix_documents_status", ...) here: the `status`
        # Column above already has index=True, which SQLAlchemy auto-names
        # ix_documents_status. Declaring both collided on create_all()
        # ("index ix_documents_status already exists").
        UniqueConstraint("sha256", name="uq_document_sha256"),
    )

    def __repr__(self):
        return f"<Document(doc_id={self.doc_id}, doc_name={self.doc_name}, status={self.status})>"
