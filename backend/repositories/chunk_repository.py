"""Chunk repository for database operations.

Provides CRUD operations for Chunk model with document relationships.
"""

import logging
from typing import Dict, List, Optional
from uuid import UUID

from models.base import Chunk
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ChunkRepository:
    """Repository for Chunk CRUD operations."""

    @staticmethod
    def create(
        session: Session,
        doc_id: UUID,
        text: str,
        checksum: str,
        page: int,
        span: Dict[str, int],
        embedding_id: str,
        section: Optional[str] = None,
        layout: Optional[Dict] = None,
        overlap: float = 0.0,
        vector_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Chunk:
        """
        Create a new chunk.

        Args:
            session: Database session
            doc_id: Parent document UUID
            text: Chunk text content
            checksum: SHA1 hash of text
            page: Page number in document
            span: Byte offsets {"start": int, "end": int}
            embedding_id: Embedding model identifier
            section: Optional section name
            layout: Optional layout metadata (bbox, block_type)
            overlap: Overlap ratio with adjacent chunks (0.0-1.0)
            vector_id: Optional Qdrant point ID
            metadata: Optional additional metadata

        Returns:
            Chunk: Created chunk instance
        """
        chunk = Chunk(
            doc_id=doc_id,
            text=text,
            checksum=checksum,
            page=page,
            section=section,
            span=span,
            layout=layout,
            overlap=overlap,
            vector_id=vector_id,
            embedding_id=embedding_id,
            chunk_metadata=metadata,
        )

        session.add(chunk)
        session.flush()
        return chunk

    @staticmethod
    def create_bulk(session: Session, chunks_data: List[Dict]) -> List[Chunk]:
        """
        Create multiple chunks in bulk (more efficient than individual creates).

        Args:
            session: Database session
            chunks_data: List of dictionaries with chunk data

        Returns:
            List of created chunk instances

        Example:
            chunks_data = [
                {
                    "doc_id": uuid4(),
                    "text": "Chunk 1",
                    "checksum": "abc123",
                    "page": 1,
                    "span": {"start": 0, "end": 7},
                    "embedding_id": "nomic-v1",
                },
                ...
            ]
        """
        chunks = []
        for data in chunks_data:
            chunk = Chunk(**data)
            chunks.append(chunk)

        session.bulk_save_objects(chunks, return_defaults=True)
        session.flush()
        return chunks

    @staticmethod
    def get_by_id(session: Session, chunk_id: UUID) -> Optional[Chunk]:
        """
        Get chunk by ID.

        Args:
            session: Database session
            chunk_id: Chunk UUID

        Returns:
            Chunk if found, None otherwise
        """
        return session.query(Chunk).filter(Chunk.chunk_id == chunk_id).first()

    @staticmethod
    def get_by_doc_id(session: Session, doc_id: UUID) -> List[Chunk]:
        """
        Get all chunks for a document, ordered by page and span.

        Args:
            session: Database session
            doc_id: Document UUID

        Returns:
            List of chunks for the document
        """
        chunks = (
            session.query(Chunk)
            .filter(Chunk.doc_id == doc_id)
            .order_by(Chunk.page, Chunk.span)
            .all()
        )
        return chunks

    @staticmethod
    def search_by_vector_ids(session: Session, vector_ids: List[str]) -> List[Chunk]:
        """
        Get chunks by their Qdrant vector IDs.

        Used to retrieve full chunk data after Qdrant search returns
        matching vector IDs.

        Args:
            session: Database session
            vector_ids: List of Qdrant point IDs

        Returns:
            List of chunks with matching vector_ids
        """
        chunks = session.query(Chunk).filter(Chunk.vector_id.in_(vector_ids)).all()
        return chunks

    @staticmethod
    def get_by_page(session: Session, doc_id: UUID, page: int) -> List[Chunk]:
        """
        Get all chunks for a specific page in a document.

        Args:
            session: Database session
            doc_id: Document UUID
            page: Page number

        Returns:
            List of chunks on the specified page
        """
        return (
            session.query(Chunk)
            .filter(Chunk.doc_id == doc_id, Chunk.page == page)
            .order_by(Chunk.span)
            .all()
        )

    @staticmethod
    def count_by_doc(session: Session, doc_id: UUID) -> int:
        """
        Count chunks for a document.

        Args:
            session: Database session
            doc_id: Document UUID

        Returns:
            Number of chunks in the document
        """
        return session.query(Chunk).filter(Chunk.doc_id == doc_id).count()

    @staticmethod
    def update_vector_id(
        session: Session, chunk_id: UUID, vector_id: str
    ) -> Optional[Chunk]:
        """
        Update the Qdrant vector ID for a chunk.

        Called after chunk is successfully indexed in Qdrant.

        Args:
            session: Database session
            chunk_id: Chunk UUID
            vector_id: Qdrant point ID

        Returns:
            Updated chunk if found, None otherwise
        """
        chunk = ChunkRepository.get_by_id(session, chunk_id)
        if chunk:
            chunk.vector_id = vector_id
            session.flush()
        return chunk

    @staticmethod
    def get_chunks_without_vectors(
        session: Session, embedding_id: str, limit: int = 100
    ) -> List[Chunk]:
        """
        Get chunks that haven't been indexed in Qdrant yet.

        Useful for batch processing chunks that need vectorization.

        Args:
            session: Database session
            embedding_id: Embedding model identifier
            limit: Maximum number of chunks to return

        Returns:
            List of chunks without vector_ids
        """
        return (
            session.query(Chunk)
            .filter(
                Chunk.embedding_id == embedding_id,
                Chunk.vector_id.is_(None),
            )
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_by_chunk_ids(session: Session, chunk_ids: List[UUID]) -> List[Chunk]:
        """
        Get chunks by their IDs efficiently.

        Args:
            session: Database session
            chunk_ids: List of chunk UUIDs

        Returns:
            List of chunks with matching IDs
        """
        if not chunk_ids:
            return []

        return session.query(Chunk).filter(Chunk.chunk_id.in_(chunk_ids)).all()

    @staticmethod
    def delete_by_doc_id(session: Session, doc_id: UUID) -> int:
        """
        Delete all chunks for a given document.

        Args:
            session: Database session
            doc_id: Document UUID

        Returns:
            Number of chunks deleted
        """
        deleted = (
            session.query(Chunk)
            .filter(Chunk.doc_id == doc_id)
            .delete(synchronize_session=False)
        )
        session.flush()
        return deleted
