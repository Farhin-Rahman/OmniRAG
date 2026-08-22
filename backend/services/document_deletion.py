"""
Unified document deletion service.

Ensures documents are deleted from all systems:
- Postgres (documents + chunks)
- Qdrant (vectors)
- File storage (raw files)
- Future: Knowledge graph nodes/edges
"""

import logging
from uuid import UUID
from sqlalchemy.orm import Session

from repositories.document_repository import DocumentRepository
from services.db.qdrant_service import get_qdrant_service
from services.storage.file_storage import get_file_storage

logger = logging.getLogger(__name__)


def delete_document_everywhere(
    db: Session, doc_id: UUID, tenant_id: UUID, idempotent: bool = True
) -> dict:
    """
    Delete a document from all systems (Postgres, Qdrant, file storage).

    This is the single source of truth for document deletion. All delete
    operations should call this function to ensure consistency.

    Args:
        db: Database session
        doc_id: Document UUID to delete
        tenant_id: Tenant UUID for isolation
        idempotent: If True, calling delete twice succeeds (default: True)

    Returns:
        dict with deletion status:
        {
            "doc_id": str,
            "deleted": bool,
            "qdrant_deleted": bool,
            "file_deleted": bool,
            "postgres_deleted": bool,
            "errors": list[str]
        }

    Raises:
        ValueError: If document not found (unless idempotent=True and already deleted)
    """
    errors = []
    result = {
        "doc_id": str(doc_id),
        "deleted": False,
        "qdrant_deleted": False,
        "file_deleted": False,
        "postgres_deleted": False,
        "errors": errors,
    }

    # Step 1: Get document metadata before deletion (needed for file deletion)
    document = DocumentRepository.get_by_id(db, doc_id, tenant_id)
    if not document:
        if idempotent:
            logger.info(f"Document {doc_id} not found (already deleted?), skipping")
            return result
        raise ValueError(f"Document {doc_id} not found for tenant {tenant_id}")

    doc_mime = document.mime

    # Step 2: Mark as deleting (tombstone) - optional, can be added to Document model later
    # For now, we proceed directly to deletion

    # Step 3: Delete from Qdrant (all collections)
    try:
        qdrant_service = get_qdrant_service()
        qdrant_deleted = qdrant_service.delete_by_doc_id(doc_id)
        result["qdrant_deleted"] = qdrant_deleted
        logger.info(f"Deleted Qdrant vectors for document {doc_id}")
    except Exception as exc:
        error_msg = f"Failed to delete Qdrant vectors: {exc}"
        errors.append(error_msg)
        logger.error(
            f"Document deletion error for {doc_id}: {error_msg}", exc_info=True
        )
        # Continue with other deletions even if Qdrant fails

    # Step 4: Delete file from storage
    try:
        file_storage = get_file_storage()
        if file_storage.file_exists(doc_id, doc_mime):
            file_deleted = file_storage.delete_file(doc_id, doc_mime)
            result["file_deleted"] = file_deleted
            logger.info(f"Deleted file for document {doc_id}")
        else:
            logger.warning(
                f"File not found for document {doc_id} (may have been deleted already)"
            )
            result["file_deleted"] = False  # Not an error if file doesn't exist
    except Exception as exc:
        error_msg = f"Failed to delete file: {exc}"
        errors.append(error_msg)
        logger.warning(
            f"Document deletion warning for {doc_id}: {error_msg}", exc_info=True
        )
        # Continue with Postgres deletion even if file deletion fails

    # Step 5: Delete from Postgres (cascades to chunks via foreign key)
    try:
        postgres_deleted = DocumentRepository.delete(db, doc_id, tenant_id)
        result["postgres_deleted"] = bool(postgres_deleted)
        if postgres_deleted:
            db.commit()
            logger.info(f"Deleted document {doc_id} from Postgres")
        else:
            if idempotent:
                logger.info(
                    f"Document {doc_id} not found in Postgres (already deleted?)"
                )
            else:
                errors.append("Document not found in Postgres")
    except Exception as exc:
        error_msg = f"Failed to delete from Postgres: {exc}"
        errors.append(error_msg)
        logger.error(
            f"Document deletion error for {doc_id}: {error_msg}", exc_info=True
        )
        db.rollback()
        # Re-raise Postgres errors as they're critical
        raise

    # Step 6: Future: Delete from knowledge graph (if enabled)
    # if settings.graph_enabled:
    #     try:
    #         graph_service.delete_document_nodes(doc_id, tenant_id)
    #         result["graph_deleted"] = True
    #     except Exception as exc:
    #         errors.append(f"Failed to delete from graph: {exc}")

    # Determine overall success
    result["deleted"] = result["postgres_deleted"] and (
        result["qdrant_deleted"] or len(errors) == 0  # Qdrant failure is non-critical
    )

    if result["deleted"]:
        logger.info(
            f"Successfully deleted document {doc_id} everywhere: "
            f"postgres={result['postgres_deleted']} "
            f"qdrant={result['qdrant_deleted']} "
            f"file={result['file_deleted']}"
        )
    else:
        logger.warning(f"Document deletion incomplete for {doc_id}: {errors}")

    return result
