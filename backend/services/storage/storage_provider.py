"""
Storage provider abstraction for document storage.

Supports multiple storage backends:
- Local filesystem (default)
- SharePoint (placeholder, not yet implemented)
- S3/Azure Blob/GCS (future)

This abstraction allows gradual migration to cloud storage without
changing the rest of the codebase.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class StorageProvider(ABC):
    """Abstract base class for storage providers."""

    @abstractmethod
    def get_file(self, doc_id: UUID, mime: str) -> bytes:
        """Retrieve file content."""
        pass

    @abstractmethod
    def file_exists(self, doc_id: UUID, mime: str) -> bool:
        """Check if file exists."""
        pass

    @abstractmethod
    def save_file(self, file_content: bytes, doc_id: UUID, mime: str) -> str:
        """Save file content."""
        pass

    @abstractmethod
    def delete_file(self, doc_id: UUID, mime: str) -> bool:
        """Delete file."""
        pass

    @abstractmethod
    def get_file_url(self, source_uri: str) -> Optional[str]:
        """
        Get accessible URL for a source URI.

        For local storage, returns None (use get_file).
        For SharePoint/HTTP sources, returns the URL or proxy URL.

        Returns:
            URL string if accessible via HTTP, None if needs download
        """
        pass


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage provider (default)."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_file(self, doc_id: UUID, mime: str) -> bytes:
        """Retrieve from local filesystem."""
        from services.storage.file_storage import FileStorageService

        storage = FileStorageService(base_dir=self.base_dir)
        return storage.get_file(doc_id, mime)

    def file_exists(self, doc_id: UUID, mime: str) -> bool:
        """Check local filesystem."""
        from services.storage.file_storage import FileStorageService

        storage = FileStorageService(base_dir=self.base_dir)
        return storage.file_exists(doc_id, mime)

    def save_file(self, file_content: bytes, doc_id: UUID, mime: str) -> str:
        """Save to local filesystem."""
        from services.storage.file_storage import FileStorageService

        storage = FileStorageService(base_dir=self.base_dir)
        return storage.save_file(file_content, doc_id, mime)

    def delete_file(self, doc_id: UUID, mime: str) -> bool:
        """Delete from local filesystem."""
        from services.storage.file_storage import FileStorageService

        storage = FileStorageService(base_dir=self.base_dir)
        return storage.delete_file(doc_id, mime)

    def get_file_url(self, source_uri: str) -> Optional[str]:
        """Local storage doesn't provide HTTP URLs."""
        return None


class SharePointStorageProvider(StorageProvider):
    """
    SharePoint storage provider (placeholder, not yet implemented).

    Future implementation will:
    - Authenticate with SharePoint using OAuth2
    - Proxy file requests through backend
    - Cache files locally for performance
    """

    def __init__(self):
        logger.warning("SharePoint storage provider is not yet implemented")

    def get_file(self, doc_id: UUID, mime: str) -> bytes:
        """Not implemented - raises error."""
        raise NotImplementedError(
            "SharePoint storage is not yet configured. "
            "Please configure SharePoint authentication and proxy settings."
        )

    def file_exists(self, doc_id: UUID, mime: str) -> bool:
        """Not implemented."""
        return False

    def save_file(self, file_content: bytes, doc_id: UUID, mime: str) -> str:
        """Not implemented."""
        raise NotImplementedError("SharePoint storage is not yet configured.")

    def delete_file(self, doc_id: UUID, mime: str) -> bool:
        """Not implemented."""
        return False

    def get_file_url(self, source_uri: str) -> Optional[str]:
        """
        Get SharePoint file URL (placeholder).

        Future: Return proxy URL that handles authentication.
        """
        if "sharepoint.com" in source_uri.lower() or "sharepoint" in source_uri.lower():
            # Future: Return proxy URL like /api/storage/sharepoint-proxy?uri=...
            logger.warning(
                f"SharePoint URL requested but proxy not configured: {source_uri}"
            )
            return None
        return None


def get_storage_provider(source_uri: Optional[str] = None) -> StorageProvider:
    """
    Get appropriate storage provider based on source URI.

    Args:
        source_uri: Optional source URI to determine provider

    Returns:
        StorageProvider instance
    """
    # Check if source_uri indicates SharePoint
    if source_uri and (
        "sharepoint.com" in source_uri.lower() or "sharepoint" in source_uri.lower()
    ):
        # Future: Return SharePoint provider when configured
        # For now, return local storage as fallback
        logger.warning(f"SharePoint source detected but not configured: {source_uri}")
        from config.settings import settings
        from pathlib import Path

        return LocalStorageProvider(Path(settings.documents_dir))

    # Default to local storage
    from config.settings import settings
    from pathlib import Path

    return LocalStorageProvider(Path(settings.documents_dir))
