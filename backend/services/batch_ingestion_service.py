"""
Batch ingestion service for processing multiple documents from a folder.

This service handles:
- Tracking processed files to avoid reprocessing
- Scanning batch input directory for supported files
- Processing files through the existing ingestion pipeline
- Error handling and reporting
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from celery import chain, group
from sqlalchemy.orm import Session

from config.settings import settings
from repositories.document_repository import DocumentRepository
from schemas.document import DocumentResponse
from schemas.events import IngestedDocumentEvent
from services.event_publisher import publish_event
from services.storage.file_storage import get_file_storage
from worker.ingestion import create_chunks, upsert_vectors

logger = logging.getLogger(__name__)


class BatchIngestionService:
    """Service for batch processing documents from a folder."""

    def __init__(self) -> None:
        self.batch_input_dir = Path(settings.batch_input_dir)
        self.processed_dir = self.batch_input_dir / "processed"
        self.tracking_file = Path(settings.batch_tracking_file)

        self.supported_extensions: set[str] = {".pdf", ".docx"}
        self.supported_mimetypes: dict[str, str] = {
            ".pdf": "application/pdf",
            ".docx": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        }

    # ------------------------------------------------------------------ #
    # Tracking helpers                                                   #
    # ------------------------------------------------------------------ #

    def _ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.batch_input_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.tracking_file.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Batch input directory: %s", self.batch_input_dir.absolute())

    def _load_processed_files(self) -> Dict[str, Dict[str, Any]]:
        """Load the tracking file containing processed files metadata."""
        if not self.tracking_file.exists():
            return {}

        try:
            with self.tracking_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Error loading tracking file %s: %s",
                self.tracking_file,
                exc,
                exc_info=True,
            )
            return {}

    def _save_processed_files(self, processed_files: Dict[str, Dict[str, Any]]) -> None:
        """Save the tracking file with processed files metadata."""
        try:
            with self.tracking_file.open("w", encoding="utf-8") as f:
                json.dump(processed_files, f, indent=2, default=str)
        except OSError as exc:
            logger.error(
                "Error saving tracking file %s: %s",
                self.tracking_file,
                exc,
                exc_info=True,
            )
            raise

    @staticmethod
    def _build_file_metadata(
        file_path: Path,
        sha256: str,
        stat,
    ) -> Dict[str, Any]:
        """
        Build file metadata for tracking purposes.
        """
        return {
            "size": stat.st_size,
            "modified_time": stat.st_mtime,
            "sha256": sha256,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _is_file_processed(
        self,
        file_path: Path,
        processed_files: Dict[str, Dict[str, Any]],
        sha256_hash: str,
        stat,
    ) -> bool:
        """
        Check if a file has already been processed using SHA and size/mtime.
        """
        filename = file_path.name
        stored_metadata = processed_files.get(filename)

        if stored_metadata is None:
            return False

        return (
            stored_metadata.get("size") == stat.st_size
            and stored_metadata.get("modified_time") == stat.st_mtime
            and stored_metadata.get("sha256") == sha256_hash
        )

    # ------------------------------------------------------------------ #
    # Scanning + per-file processing                                     #
    # ------------------------------------------------------------------ #

    def _scan_batch_directory(self) -> List[Path]:
        """Scan batch directory for supported files (recursively)."""
        if not self.batch_input_dir.exists():
            logger.warning(
                "Batch input directory does not exist: %s",
                self.batch_input_dir,
            )
            return []

        files: list[Path] = []
        # Scan recursively to include subdirectories
        for file_path in self.batch_input_dir.rglob("*"):
            if (
                file_path.is_file()
                and file_path.suffix.lower() in self.supported_extensions
                # Exclude files in 'processed' subdirectory
                and "processed" not in file_path.parts
            ):
                files.append(file_path)

        logger.info(
            "Found %d supported files in batch directory (recursive scan)", len(files)
        )
        return files

    def _process_single_file(
        self,
        file_path: Path,
        tenant_id: UUID,
        db: Session,
        content: bytes,
        sha256_hash: str,
        stat,
        source_uri: Optional[str] = None,
    ) -> Tuple[
        bool, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Any]
    ]:
        """
        Process a single file through the ingestion pipeline.

        Returns:
            (success, message, document_data, file_metadata_for_tracking, chain_signature)
        """
        try:
            # Check for duplicate document (per tenant)
            # DEMO HACK: Disable duplicate check to allow showing "Sync" repeatedly
            # existing_doc = DocumentRepository.get_by_sha256(
            #     db,
            #     sha256_hash,
            #     tenant_id,
            # )
            # if existing_doc:
            #     msg = (
            #         f"Document already exists (duplicate SHA256): {existing_doc.doc_id}"
            #     )
            #     logger.info(
            #         "Skipping duplicate document for tenant %s: %s",
            #         tenant_id,
            #         existing_doc.doc_id,
            #     )
            #     return False, msg, None, None, None

            # Determine MIME type
            file_extension = file_path.suffix.lower()
            mime_type = self.supported_mimetypes.get(
                file_extension,
                "application/octet-stream",
            )

            # Use provided source_uri or default to batch://
            final_source_uri = source_uri if source_uri else f"batch://{file_path.name}"

            ingest_run_id = uuid4()
            document = DocumentRepository.create(
                session=db,
                sha256=sha256_hash,
                mime=mime_type,
                pages=0,
                source_uri=final_source_uri,
                doc_name=file_path.stem,
                ingest_run_id=ingest_run_id,
                doc_type=file_extension[1:],  # Remove the dot
                tenant_id=tenant_id,
                embedding_id=settings.embedding_model,
                status="queued",
                version=1,
            )

            # Flush to get doc_id without committing
            db.flush()

            # Save file to storage
            file_storage = get_file_storage()
            stored_path = file_storage.save_file(content, document.doc_id, mime_type)
            logger.info(
                "Saved file for document %s at %s",
                document.doc_id,
                stored_path,
            )

            # Commit DB state after file is stored
            db.commit()

            # Publish initial ingest event
            event = IngestedDocumentEvent(
                doc_id=document.doc_id,
                sha256=document.sha256,
                pages=document.pages,
                tenant_id=document.tenant_id,
                ingest_run_id=document.ingest_run_id,
            )
            publish_event("ingest.document.v1", event)

            # Dispatch Celery processing chain
            document_response = DocumentResponse.model_validate(document)
            document_data = document_response.model_dump()

            processing_chain = chain(
                create_chunks.s(document_data=document_data),
                upsert_vectors.s(),
            )

            # Build tracking metadata without re-reading the file
            file_metadata = self._build_file_metadata(file_path, sha256_hash, stat)

            return (
                True,
                f"Successfully queued document: {document.doc_id}",
                document_data,
                file_metadata,
                processing_chain,
            )

        except Exception as exc:  # noqa: BLE001
            # Ensure DB state is clean for subsequent files
            db.rollback()
            error_msg = f"Error processing file {file_path.name}: {exc}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, None, None, None

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def process_batch(self, tenant_id: str, db: Session) -> Dict[str, Any]:
        """
        Process all new files in the batch directory.

        Args:
            tenant_id: Tenant ID for document ownership (string UUID).
            db: Database session.

        Returns:
            Dictionary containing processing summary.
        """
        self._ensure_directories()

        tenant_uuid = UUID(tenant_id)
        processed_files_tracker = self._load_processed_files()

        # Scan for files and precompute hash/stat once
        files_to_process = self._scan_batch_directory()
        files_info = []
        for file_path in files_to_process:
            try:
                stat = file_path.stat()
                with file_path.open("rb") as f:
                    content = f.read()
                sha256_hash = hashlib.sha256(content).hexdigest()
            except OSError as exc:
                logger.error(
                    "Skipping file %s due to read error: %s", file_path.name, exc
                )
                continue

            if self._is_file_processed(
                file_path, processed_files_tracker, sha256_hash, stat
            ):
                logger.info("Skipping already processed file: %s", file_path.name)
                continue

            files_info.append((file_path, content, sha256_hash, stat))

        logger.info("Found %d new files to process", len(files_info))

        results: Dict[str, Any] = {
            "processed": 0,
            "failed": 0,
            "skipped": len(files_to_process) - len(files_info),
            "total_found": len(files_to_process),
            "details": [],
        }

        chain_sigs = []

        # Build chains; dispatch after the loop for parallelism
        for file_path, content, sha256_hash, stat in files_info:
            logger.info("Processing file: %s", file_path.name)

            # Use a fresh session per file for isolation
            from services.db.postgres_service import (
                SessionLocal,
            )  # local import to avoid cycles

            file_db = SessionLocal()
            try:
                success, message, document_data, file_metadata, chain_sig = (
                    self._process_single_file(
                        file_path=file_path,
                        tenant_id=tenant_uuid,
                        db=file_db,
                        content=content,
                        sha256_hash=sha256_hash,
                        stat=stat,
                    )
                )
                file_db.commit()
            except Exception:
                file_db.rollback()
                raise
            finally:
                file_db.close()

            file_detail: Dict[str, Any] = {
                "filename": file_path.name,
                "success": success,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            if success:
                results["processed"] += 1
                if document_data:
                    file_detail["doc_id"] = document_data.get("doc_id")

                if chain_sig is not None:
                    chain_sigs.append(chain_sig)

                # Update tracking using metadata returned by _process_single_file
                if file_metadata:
                    processed_files_tracker[file_path.name] = file_metadata
                # Move processed file to processed/ to avoid re-scan noise
                try:
                    target_path = self.processed_dir / file_path.name
                    file_path.rename(target_path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Could not move processed file %s: %s", file_path.name, exc
                    )
            else:
                results["failed"] += 1

            results["details"].append(file_detail)

        if chain_sigs:
            max_parallel = max(1, getattr(settings, "batch_max_parallel", 10))
            for i in range(0, len(chain_sigs), max_parallel):
                chunk = chain_sigs[i : i + max_parallel]
                group_result = group(chunk).apply_async()
                logger.info(
                    "Dispatched %d ingestion chains (group id=%s)",
                    len(chunk),
                    group_result.id,
                )

        # Save updated tracking file (best-effort; don't fail batch on this)
        if results["processed"] > 0:
            try:
                self._save_processed_files(processed_files_tracker)
                logger.info(
                    "Updated tracking file with %d new entries",
                    results["processed"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to update tracking file %s: %s",
                    self.tracking_file,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Batch processing complete. Processed: %d, Failed: %d, Skipped: %d",
            results["processed"],
            results["failed"],
            results["skipped"],
        )

        return results


# Singleton instance
_batch_service: BatchIngestionService | None = None


def get_batch_ingestion_service() -> BatchIngestionService:
    """Get singleton BatchIngestionService instance."""
    global _batch_service  # noqa: PLW0603
    if _batch_service is None:
        _batch_service = BatchIngestionService()
    return _batch_service
