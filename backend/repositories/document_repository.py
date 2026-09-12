"""Document repository for database operations."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from models.base import Document
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Repository for Document CRUD operations."""

    @staticmethod
    def create(
        session: Session,
        sha256: str,
        mime: str,
        pages: int,
        source_uri: str,
        doc_name: str,
        ingest_run_id: UUID,
        doc_type: str,
        embedding_id: str,
        status: str = "queued",
        version: int = 1,
    ) -> Document:
        document = Document(
            sha256=sha256,
            mime=mime,
            pages=pages,
            source_uri=source_uri,
            doc_name=doc_name,
            ingest_run_id=ingest_run_id,
            doc_type=doc_type,
            status=status,
            version=version,
            embedding_id=embedding_id,
            created_at=datetime.now(timezone.utc),
        )

        session.add(document)
        session.flush()
        return document

    @staticmethod
    def get(session: Session, doc_id: UUID) -> Optional[Document]:
        return session.query(Document).filter(Document.doc_id == doc_id).first()

    @staticmethod
    def get_by_sha256(session: Session, sha256: str) -> Optional[Document]:
        return session.query(Document).filter(Document.sha256 == sha256).first()

    @staticmethod
    def update_status(
        session: Session, doc_id: UUID, status: str
    ) -> Optional[Document]:
        document = DocumentRepository.get(session, doc_id)
        if document:
            document.status = status
            session.flush()
        return document

    @staticmethod
    def list_documents(
        session: Session,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> List[Document]:
        query = session.query(Document)

        if status:
            query = query.filter(Document.status == status)
        if doc_type:
            query = query.filter(Document.doc_type == doc_type)

        return (
            query.order_by(Document.created_at.desc()).limit(limit).offset(offset).all()
        )

    @staticmethod
    def delete(session: Session, doc_id: UUID) -> bool:
        document = DocumentRepository.get(session, doc_id)
        if document:
            session.delete(document)
            session.flush()
            return True
        return False
