"""File storage service for uploaded documents.

Handles saving and retrieving document files from local filesystem.
In production, this can be extended to use S3, Azure Blob, or GCS.
"""

import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from config.settings import settings

logger = logging.getLogger(__name__)


class FileStorageService:
    """Service for storing and retrieving document files."""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize file storage service.

        Args:
            base_dir: Base directory for file storage. Defaults to settings.documents_dir
        """
        if base_dir:
            self.base_dir = base_dir
        else:
            # Use absolute path if configured, otherwise relative to current directory
            if settings.documents_dir.startswith("/"):
                self.base_dir = Path(settings.documents_dir)
            else:
                self.base_dir = Path(settings.documents_dir).resolve()
        self._ensure_base_dir()

    def _ensure_base_dir(self):
        """Create base directory if it doesn't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"File storage base directory: {self.base_dir.absolute()}")

    def _get_file_path(self, doc_id: UUID, mime: str) -> Path:
        """
        Get file path for a document.

        Uses structure: data/documents/{tenant_id}/{doc_id}.{extension}

        Args:
            doc_id: Document UUID
            mime: MIME type for extension detection

        Returns:
            Path object for the file
        """
        # Determine extension from MIME type
        extension_map = {
            "application/pdf": "pdf",
            "application/msword": "doc",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
            "text/plain": "txt",
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
        }

        extension = extension_map.get(mime, "bin")
        filename = f"{doc_id}.{extension}"

        return self.base_dir / filename

    def _get_temp_file_path(
        self, user_id: UUID, filename: str, tenant_id: Optional[str] = None
    ) -> Path:
        """Build a safe temp-file path scoped per tenant + user."""
        safe_name = filename.replace("/", "_").replace("\\", "_")
        if tenant_id:
            # Path: temp/{tenant_id}/{user_id}/{filename}
            return self.base_dir / "temp" / tenant_id / str(user_id) / safe_name
        else:
            # Fallback: temp/{user_id}/{filename}
            return self.base_dir / "temp" / str(user_id) / safe_name

    def save_file(self, file_content: bytes, doc_id: UUID, mime: str) -> str:
        """
        Save file content to disk.

        Args:
            file_content: Binary content of the file
            doc_id: Document UUID
            mime: MIME type

        Returns:
            File path (relative to base dir) where file was saved

        Raises:
            IOError: If file cannot be written
        """
        file_path = self._get_file_path(doc_id, mime)

        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            with open(file_path, "wb") as f:
                f.write(file_content)

            logger.info(f"Saved file: {file_path} ({len(file_content)} bytes)")

            # Return the full absolute path for consistency
            return str(file_path)

        except Exception as e:
            logger.error(f"Failed to save file {file_path}: {e}", exc_info=True)
            raise IOError(f"Failed to save file: {e}") from e

    def save_temp_file(
        self,
        user_id: UUID,
        file_name: str,
        file_content: bytes,
        mime: str,
        tenant_id: Optional[str] = None,
    ) -> str:
        """
        Save a temporary file scoped to a tenant and user.

        Args:
            user_id: User UUID (from JWT)
            file_name: Original filename
            file_content: Binary content
            mime: MIME type (informational)
            tenant_id: Optional tenant ID for path scoping

        Returns:
            Absolute path to saved file as string
        """
        file_path = self._get_temp_file_path(user_id, file_name, tenant_id)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(file_path, "wb") as f:
                f.write(file_content)
            logger.info(
                "Saved temp file for tenant=%s user=%s: %s (%s bytes, mime=%s)",
                tenant_id or "<none>",
                user_id,
                file_path,
                len(file_content),
                mime,
            )
            return str(file_path)
        except Exception as e:
            logger.error(f"Failed to save temp file {file_path}: {e}", exc_info=True)
            raise IOError(f"Failed to save temp file: {e}") from e

    def get_file(self, doc_id: UUID, mime: str) -> bytes:
        """
        Retrieve file content from disk.

        Args:
            doc_id: Document UUID
            mime: MIME type

        Returns:
            Binary content of the file

        Raises:
            FileNotFoundError: If file doesn't exist
            IOError: If file cannot be read
        """
        file_path = self._get_file_path(doc_id, mime)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "rb") as f:
                content = f.read()

            logger.info(f"Retrieved file: {file_path} ({len(content)} bytes)")
            return content

        except Exception as e:
            logger.error(f"Failed to read file {file_path}: {e}", exc_info=True)
            raise IOError(f"Failed to read file: {e}") from e

    def file_exists(self, doc_id: UUID, mime: str) -> bool:
        """
        Check if file exists.

        Args:
            doc_id: Document UUID
            mime: MIME type

        Returns:
            True if file exists, False otherwise
        """
        file_path = self._get_file_path(doc_id, mime)
        return file_path.exists()

    def delete_file(self, doc_id: UUID, mime: str) -> bool:
        """
        Delete file from disk.

        Args:
            doc_id: Document UUID
            mime: MIME type

        Returns:
            True if file was deleted, False if file didn't exist

        Raises:
            IOError: If file cannot be deleted
        """
        file_path = self._get_file_path(doc_id, mime)

        if not file_path.exists():
            logger.warning(f"File not found for deletion: {file_path}")
            return False

        try:
            file_path.unlink()
            logger.info(f"Deleted file: {file_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}", exc_info=True)
            raise IOError(f"Failed to delete file: {e}") from e

    def get_file_size(self, doc_id: UUID, mime: str) -> int:
        """
        Get file size in bytes.

        Args:
            doc_id: Document UUID
            mime: MIME type

        Returns:
            File size in bytes

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        file_path = self._get_file_path(doc_id, mime)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        return file_path.stat().st_size


# Singleton instance
_file_storage = None


def get_file_storage() -> FileStorageService:
    """
    Get singleton FileStorageService instance.

    Returns:
        FileStorageService instance
    """
    global _file_storage
    if _file_storage is None:
        _file_storage = FileStorageService()
    return _file_storage
