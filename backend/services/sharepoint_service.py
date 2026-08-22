import asyncio
import logging
from typing import Optional


logger = logging.getLogger(__name__)


class SharePointService:
    _instance: Optional["SharePointService"] = None
    _is_syncing: bool = False
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SharePointService, cls).__new__(cls)
        return cls._instance

    @classmethod
    def is_syncing(cls) -> bool:
        """Check if a sync is currently in progress."""
        return cls._is_syncing

    @classmethod
    async def run_sync(cls, tenant_id: str):
        """
        Run the SharePoint sync process.
        This method ensures only one sync runs at a time.
        """
        from utils.sharepoint_sync import SharePointSync

        async with cls._lock:
            if cls._is_syncing:
                logger.warning("Sync already in progress, skipping request.")
                return
            cls._is_syncing = True

        try:
            logger.info(f"Starting SharePoint sync for tenant {tenant_id}")
            syncer = SharePointSync(target_tenant_id=tenant_id)
            await syncer.sync()
            logger.info("SharePoint sync completed successfully")
        except Exception as e:
            logger.error(f"SharePoint sync failed: {e}", exc_info=True)
        finally:
            cls._is_syncing = False

    @classmethod
    async def list_files(
        cls, tenant_id: str, exclude_paths=None, folder_path=None, min_date=None
    ):
        """
        Get list of all SharePoint PDF files without downloading.
        Returns list of file metadata dicts.
        """
        from utils.sharepoint_sync import SharePointSync

        try:
            logger.info(f"Listing SharePoint files for tenant {tenant_id}")
            syncer = SharePointSync(target_tenant_id=tenant_id)
            files = await syncer.list_files_search(
                exclude_paths=exclude_paths, folder_path=folder_path, min_date=min_date
            )
            logger.info(f"Found {len(files)} files in SharePoint")
            return files
        except Exception as e:
            logger.error(f"Failed to list SharePoint files: {e}", exc_info=True)
            raise

    @classmethod
    async def sync_file(cls, tenant_id: str, item_id: str):
        """
        Sync a single file by SharePoint item_id.
        Returns dict with success status and message.
        """
        from utils.sharepoint_sync import SharePointSync

        try:
            logger.info(f"Syncing single file {item_id} for tenant {tenant_id}")
            syncer = SharePointSync(target_tenant_id=tenant_id)
            result = await syncer.sync_single_file(item_id)
            logger.info(f"Single file sync result: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to sync file {item_id}: {e}", exc_info=True)
            return {"success": False, "message": f"Error syncing file: {str(e)}"}

    @classmethod
    async def sync_batch(cls, tenant_id: str, item_ids: list[str]):
        """
        Sync a batch of files by their item_ids.
        Returns list of results.
        """
        from utils.sharepoint_sync import SharePointSync

        try:
            logger.info(
                f"Syncing batch of {len(item_ids)} files for tenant {tenant_id}"
            )
            syncer = SharePointSync(target_tenant_id=tenant_id)
            results = await syncer.sync_batch(item_ids)
            logger.info(f"Batch sync complete. Results count: {len(results)}")
            return results
        except Exception as e:
            logger.error(f"Failed to sync batch: {e}", exc_info=True)
            return []
