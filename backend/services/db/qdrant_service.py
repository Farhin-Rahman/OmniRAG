import logging
from typing import Any, Dict
from uuid import UUID

from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from config.settings import settings

logger = logging.getLogger(__name__)


class QdrantDimensionMismatchError(Exception):
    """Raised when Qdrant collection vector dimension mismatches the configured embedding dim."""

    def __init__(self, existing_dim: int | None, expected_dim: int):
        self.existing_dim = existing_dim
        self.expected_dim = expected_dim
        super().__init__(
            f"Qdrant collection dimension mismatch: existing={existing_dim}, expected={expected_dim}"
        )


class QdrantSearchService:
    """Production-ready Qdrant vector search service."""

    def __init__(self, host: str | None = None, port: int | None = None) -> None:
        """
        Initialize Qdrant search service.

        Args:
            host: Qdrant host (defaults to settings.qdrant_host)
            port: Qdrant port (defaults to settings.qdrant_port)
        """
        self.host = host or settings.qdrant_host
        self.port = port or settings.qdrant_port

        # You could also use url=settings.qdrant_url if you have TLS / Cloud
        self.client = QdrantClient(host=self.host, port=self.port)
        logger.info("Qdrant service initialized: %s:%s", self.host, self.port)

    def search(
        self,
        query_vector: list[float],
        tenant_id: str | None = None,
        k: int = 10,
        filters: Dict[str, Any] | None = None,
        embedding_id: str | None = None,
        doc_ids: list[str] | None = None,
        acl_filter: models.Filter | Dict[str, Any] | None = None,
    ) -> list[Dict[str, Any]]:
        """
        Perform chunk-level vector search with filters.

        Args:
            query_vector: Query embedding vector.
            tenant_id: Tenant UUID for isolation (used if acl_filter not provided).
            k: Number of results to return.
            filters: Additional filters (doc_type, status, etc.).
            embedding_id: Embedding model identifier.
            doc_ids: Optional list of doc_ids to constrain the search to.
            acl_filter: Pre-built Qdrant Filter for ACL enforcement (overrides tenant_id logic).

        Returns:
            List of search results with chunk_id, score, page, section, and metadata.
        """
        # Base filter construction
        if acl_filter:
            # Use provided ACL filter as base (can be dict or models.Filter)
            if isinstance(acl_filter, dict):
                query_filter = models.Filter(**acl_filter)
            else:
                query_filter = acl_filter
        else:
            # Legacy/Fallback: Construct basics
            filter_conditions: list[models.FieldCondition] = []
            if tenant_id:
                filter_conditions.append(
                    models.FieldCondition(
                        key="tenant_id",
                        match=models.MatchValue(value=str(tenant_id)),
                    ),
                )
            query_filter = models.Filter(must=filter_conditions)

        # Merge additional constraints (embedding_id, doc_type, doc_ids) into 'must'
        # Ensure 'must' exists
        if not query_filter.must:
            query_filter.must = []

        if embedding_id:
            query_filter.must.append(
                models.FieldCondition(
                    key="embedding_id",
                    match=models.MatchValue(value=embedding_id),
                )
            )

        if filters:
            doc_type = filters.get("doc_type")
            if doc_type:
                query_filter.must.append(
                    models.FieldCondition(
                        key="doc_type",
                        match=models.MatchValue(value=doc_type),
                    )
                )

        if doc_ids:
            query_filter.must.append(
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchAny(any=doc_ids),
                )
            )

        # Optimize filter: if no conditions, set to None
        if not query_filter.must and not query_filter.should:
            query_filter = None

        try:
            # Query API on chunk collection
            search_result = self.client.query_points(
                collection_name=settings.qdrant_chunk_collection,
                query=query_vector,
                query_filter=query_filter,
                limit=k,
                with_payload=True,
            )

            formatted_results: list[Dict[str, Any]] = []
            points = getattr(search_result, "points", []) or []
            for hit in points:
                payload = hit.payload or {}
                text = payload.get("text")
                formatted_results.append(
                    {
                        "chunk_id": payload.get("chunk_id"),
                        "doc_id": payload.get("doc_id"),
                        "doc_name": payload.get("doc_name"),
                        "score": hit.score,
                        "page": payload.get("page"),
                        "section": payload.get("section"),
                        "text": text,
                        "content": text,  # alias expected by downstream code
                        "metadata": payload,
                    },
                )

            logger.info(
                "Search returned %s results (acl_filter=%s)",
                len(formatted_results),
                bool(acl_filter),
            )
            return formatted_results

        except UnexpectedResponse as exc:
            # Handle common Qdrant dimension mismatch gracefully
            raw = getattr(exc, "response", None)
            raw_text = getattr(raw, "content", b"") if raw else b""
            raw_text_str = raw_text.decode("utf-8", errors="ignore")
            if "Vector dimension error" in raw_text_str:
                logger.error("Qdrant dimension mismatch detected: %s", raw_text_str)
                raise QdrantDimensionMismatchError(
                    existing_dim=None, expected_dim=settings.embedding_dim
                ) from exc
            logger.error("Qdrant search failed: %s", exc, exc_info=True)
            raise
        except Exception as exc:
            logger.error("Qdrant search failed: %s", exc, exc_info=True)
            raise

    def upsert_chunks(
        self,
        chunks_data: list[Dict[str, Any]],
        collection_name: str | None = None,
    ) -> int:
        """
        Upsert chunks into a Qdrant collection.

        Args:
            chunks_data: List of chunk data:
                [{"chunk_id": "uuid", "vector": [...], "payload": {...}}, ...]
            collection_name: Collection name (defaults to chunk collection).

        Returns:
            Number of chunks upserted.
        """
        collection = collection_name or settings.qdrant_chunk_collection

        points: list[models.PointStruct] = []
        for chunk in chunks_data:
            points.append(
                models.PointStruct(
                    id=chunk["chunk_id"],
                    vector=chunk["vector"],
                    payload=chunk.get("payload", {}),
                ),
            )

        try:
            self.client.upsert(
                collection_name=collection,
                points=points,
            )
            logger.info(
                "Upserted %s chunks to Qdrant collection '%s'",
                len(points),
                collection,
            )
            return len(points)

        except Exception as exc:
            logger.error(
                "Failed to upsert chunks to Qdrant collection '%s': %s",
                collection,
                exc,
                exc_info=True,
            )
            raise

    def delete_by_doc_id(
        self,
        doc_id: UUID,
        collection_name: str | None = None,
    ) -> bool:
        """
        Delete all chunks for a document from Qdrant.

        Args:
            doc_id: Document UUID.
            collection_name: Collection name (defaults to chunk collection).

        Returns:
            True if deletion completed without error.
        """
        collection = collection_name or settings.qdrant_chunk_collection

        try:
            self.client.delete(
                collection_name=collection,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="doc_id",
                                match=models.MatchValue(value=str(doc_id)),
                            ),
                        ],
                    ),
                ),
            )
            logger.info(
                "Deleted chunks for document %s from Qdrant collection '%s'",
                doc_id,
                collection,
            )
            return True

        except Exception as exc:
            logger.error(
                "Failed to delete chunks for document %s from Qdrant: %s",
                doc_id,
                exc,
                exc_info=True,
            )
            raise

    def update_acl_payload(
        self,
        doc_id: str,
        acl_users: list[str],
        acl_groups: list[str],
        collection_name: str | None = None,
    ) -> int:
        """
        Update ACL fields for all chunks belonging to a document.

        Args:
            doc_id: Document UUID as string.
            acl_users: List of user IDs with read access.
            acl_groups: List of group IDs with read access.
            collection_name: Collection name (defaults to chunk collection).

        Returns:
            Count of points matched when count succeeds, otherwise 0.
        """
        collection = collection_name or settings.qdrant_chunk_collection
        payload = {"acl_users": acl_users, "acl_groups": acl_groups}

        selector = models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchValue(value=str(doc_id)),
                    ),
                ],
            ),
        )

        matched = 0
        try:
            count_result = self.client.count(
                collection_name=collection,
                count_filter=selector.filter,
                exact=True,
            )
            matched = getattr(count_result, "count", 0) or 0
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Unable to count points for ACL payload update doc_id=%s: %s",
                doc_id,
                exc,
            )

        try:
            self.client.set_payload(
                collection_name=collection,
                payload=payload,
                points_selector=selector,
            )
            logger.info(
                "Updated ACL payload for doc_id=%s (matched=%d)",
                doc_id,
                matched,
            )
        except Exception as exc:
            logger.error(
                "Failed to update ACL payload for doc_id=%s: %s",
                doc_id,
                exc,
                exc_info=True,
            )
            raise

        return matched


# Singleton instance used by the rest of the app
_qdrant_service: QdrantSearchService | None = None


def get_qdrant_service() -> QdrantSearchService:
    """
    Get singleton QdrantSearchService instance.

    Returns:
        QdrantSearchService instance.
    """
    global _qdrant_service  # noqa: PLW0603
    if _qdrant_service is None:
        _qdrant_service = QdrantSearchService()
    return _qdrant_service


class QdrantService:
    """
    Utility service for collection management (create, index, initialize).

    This is separate from QdrantSearchService so you can:
    - Manage collections at startup.
    - Keep search/query logic focused in QdrantSearchService.
    """

    def __init__(
        self,
        host: str = settings.qdrant_host,
        port: int = settings.qdrant_port,
    ) -> None:
        try:
            self.client = QdrantClient(host=host, port=port)
            logger.info("Connected to Qdrant successfully at %s:%s", host, port)
        except Exception as exc:
            logger.error("Failed to connect to Qdrant: %s", exc, exc_info=True)
            raise

    def create_collection_if_not_exists(self, collection_name: str) -> None:
        """
        Ensure a collection exists with the correct vector configuration and indexes.
        Recreates collection if dimension mismatch is detected.
        """
        try:
            existing_collection = self.client.get_collection(collection_name)
            # Get vector size - handle different Qdrant API versions
            try:
                # Try new API structure
                existing_dim = existing_collection.config.params.vectors.size
            except (AttributeError, TypeError):
                try:
                    # Try alternative structure
                    existing_dim = existing_collection.config.vectors.size
                except (AttributeError, TypeError):
                    # Fallback: try to get from params directly
                    vectors_config = existing_collection.config.params.get(
                        "vectors", {}
                    )
                    if isinstance(vectors_config, dict):
                        existing_dim = vectors_config.get(
                            "size", settings.embedding_dim
                        )
                    else:
                        existing_dim = getattr(
                            vectors_config, "size", settings.embedding_dim
                        )

            expected_dim = settings.embedding_dim

            if existing_dim != expected_dim:
                logger.warning(
                    "Collection '%s' has dimension mismatch: existing=%d, expected=%d. Recreating collection...",
                    collection_name,
                    existing_dim,
                    expected_dim,
                )
                # Recreate collection with correct dimension
                self.client.recreate_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=expected_dim,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(
                    "Collection '%s' recreated with dimension %d",
                    collection_name,
                    expected_dim,
                )
                self._ensure_payload_indexes(collection_name)
            else:
                logger.info(
                    "Collection '%s' already exists with correct dimension %d",
                    collection_name,
                    existing_dim,
                )
                self._ensure_payload_indexes(collection_name)
        except Exception as e:
            # Collection doesn't exist or error accessing it, create/recreate it
            logger.info(
                "Creating/recreating collection '%s' (error: %s)",
                collection_name,
                str(e),
            )
            self.client.recreate_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=settings.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(
                "Collection '%s' created with dimension %d",
                collection_name,
                settings.embedding_dim,
            )
            self._ensure_payload_indexes(collection_name)

    def _ensure_payload_indexes(self, collection_name: str) -> None:
        """Create payload indexes for frequently filtered fields."""
        try:
            index_fields = [
                "tenant_id",
                "embedding_id",
                "doc_type",
                "doc_id",
                # Document-level metadata to support ACL-ready filtering
                "source_uri",
                "mime",
                "status",
            ]

            for field in index_fields:
                try:
                    self.client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    )
                    logger.info(
                        "Created index on '%s' for collection '%s'",
                        field,
                        collection_name,
                    )
                except Exception as exc:
                    # Most likely index already exists; debug-level log is enough.
                    logger.debug(
                        "Index on '%s' for collection '%s' might already exist: %s",
                        field,
                        collection_name,
                        exc,
                    )

        except Exception as exc:
            logger.warning(
                "Failed to create payload indexes for collection '%s': %s",
                collection_name,
                exc,
            )

    def initialize_qdrant_collection(self) -> None:
        """
        Initialize chunk collection with proper vector params and indexes.
        """
        logger.info("Initializing Qdrant collections")
        collection_name = settings.qdrant_chunk_collection

        # Force check and recreate if dimension mismatch
        try:
            existing_collection = self.client.get_collection(collection_name)
            # Get vector size - handle different Qdrant API versions
            try:
                existing_dim = existing_collection.config.params.vectors.size
            except (AttributeError, TypeError):
                try:
                    existing_dim = existing_collection.config.vectors.size
                except (AttributeError, TypeError):
                    # If we can't determine, force recreate
                    logger.warning(
                        "Cannot determine collection dimension, forcing recreation"
                    )
                    existing_dim = -1

            expected_dim = settings.embedding_dim

            if existing_dim != expected_dim:
                logger.warning(
                    "Collection '%s' dimension mismatch: existing=%d, expected=%d. FORCING RECREATION...",
                    collection_name,
                    existing_dim,
                    expected_dim,
                )
                # Delete and recreate
                try:
                    self.client.delete_collection(collection_name)
                    logger.info("Deleted old collection '%s'", collection_name)
                except Exception as del_err:
                    logger.warning(
                        "Error deleting collection (may not exist): %s", del_err
                    )

                # Create with correct dimension
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=expected_dim,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(
                    "Collection '%s' recreated with dimension %d",
                    collection_name,
                    expected_dim,
                )
                self._ensure_payload_indexes(collection_name)
            else:
                logger.info(
                    "Collection '%s' has correct dimension %d",
                    collection_name,
                    existing_dim,
                )
                self._ensure_payload_indexes(collection_name)
        except Exception as e:
            # Collection doesn't exist, create it
            logger.info(
                "Collection '%s' doesn't exist or error accessing it, creating new one: %s",
                collection_name,
                str(e),
            )
            try:
                self.client.delete_collection(collection_name)
            except Exception:
                pass  # Collection may not exist
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=settings.embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(
                "Collection '%s' created with dimension %d",
                collection_name,
                settings.embedding_dim,
            )
            self._ensure_payload_indexes(collection_name)
