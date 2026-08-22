import asyncio
import argparse
import hashlib
import json
import os
import urllib.parse
from datetime import datetime
from pathlib import Path
from uuid import UUID

# Add to import
# sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from services.batch_ingestion_service import BatchIngestionService
from services.db.postgres_service import SessionLocal

import logging

# disable verbose logging from hpack
logging.getLogger("hpack").setLevel(logging.WARNING)

from msgraph import GraphServiceClient
from azure.identity import ClientSecretCredential

from msgraph.generated.search.query.query_request_builder import QueryRequestBuilder
from msgraph.generated.models.search_request import SearchRequest
from msgraph.generated.models.entity_type import EntityType
from msgraph.generated.models.search_query import SearchQuery
from msgraph.generated.models.sort_property import SortProperty
from msgraph.generated.search.query.query_post_request_body import QueryPostRequestBody

CLIENT_ID = settings.sharepoint_client_id
CLIENT_SECRET = settings.sharepoint_client_secret
TENANT_ID = settings.sharepoint_tenant_id
SITE_ID = settings.sharepoint_site_id

LOCAL_SYNC_DIR = settings.documents_dir


class SharePointSync:
    def __init__(self, target_tenant_id: str):
        self.credential = ClientSecretCredential(
            tenant_id=TENANT_ID, client_id=CLIENT_ID, client_secret=CLIENT_SECRET
        )
        self.client = GraphServiceClient(self.credential)
        self.drive_id = None  # Will be fetched dynamically
        self.target_tenant_id = UUID(target_tenant_id)
        # Fix: Per-tenant state file to prevent cross-talk
        self.state_file = f"sync_state_{target_tenant_id}.json"

        self.batch_service = BatchIngestionService()
        self.processed_count = 0
        self.ensure_local_dir()

        self.region = "EMEA"  # Default fallback
        self.drive_web_url = None

        # Load state (delta link + file mapping for deletions)
        self.state = self.load_state()

    def ensure_local_dir(self):
        if not os.path.exists(LOCAL_SYNC_DIR):
            os.makedirs(LOCAL_SYNC_DIR)

    def load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, "r") as f:
                return json.load(f)
        return {"deltaLink": None, "fileMap": {}}

    def save_state(self, delta_link=None):
        if delta_link:
            self.state["deltaLink"] = delta_link
        with open(self.state_file, "w") as f:
            json.dump(self.state, f, indent=4)

    async def initialize_drive(self):
        """Fetches the default Drive ID associated with the Site."""
        print(f"[{datetime.now()}] Fetching default Drive for Site: {SITE_ID}...")
        try:
            # This endpoint gets the default 'Documents' library for the site
            drive = await self.client.sites.by_site_id(SITE_ID).drive.get()
            self.drive_id = drive.id
            print(f"  [FOUND] Drive ID: {self.drive_id}")
        except Exception as e:
            print(f"  [ERROR] Could not find default drive: {e}")
            raise e

    async def get_site_region(self):
        """Fetches the dataLocationCode (Region) from the Site."""
        print(f"[{datetime.now()}] Fetching Site Region...")
        try:
            site = await self.client.sites.by_site_id(SITE_ID).get()
            if site.site_collection and site.site_collection.data_location_code:
                self.region = site.site_collection.data_location_code
                print(f"  [INFO] Detected Region: {self.region}")
            else:
                print(
                    f"  [WARN] Could not detect region from site. Using default: {self.region}"
                )
        except Exception as e:
            print(
                f"  [WARN] Failed to fetch site region ({e}). Using default: {self.region}"
            )

    async def get_drive_details(self):
        """Fetches the ID and Web URL of the default drive."""
        print(f"[{datetime.now()}] Fetching Drive details...")
        drive = await self.client.sites.by_site_id(SITE_ID).drive.get()
        self.drive_id = drive.id
        self.drive_web_url = drive.web_url
        print(f"  [FOUND] Drive ID: {self.drive_id}")
        return drive.id, drive.web_url

    async def list_files_search(
        self, exclude_paths=None, folder_path=None, min_date=None
    ):
        """
        List files using Search API.
        Mimics logic:
        - If no folder_path: recent 500 files.
        - If folder_path: all files in folder.
        """
        if exclude_paths is None:
            exclude_paths = set()

        # Ensure we have region and drive details
        await self.get_site_region()
        await self.get_drive_details()

        print(f"  [INFO] Searching inside: {self.drive_web_url}")

        search_path = self.drive_web_url
        if folder_path:
            clean_folder = folder_path.strip("/")
            search_path = f"{self.drive_web_url}/{clean_folder}"

        print(f"  [INFO] Searching path: {search_path}")

        # Query Construction
        query_text = f'filetype:pdf AND path:"{search_path}"'
        if min_date:
            print(f"  [FILTER] Applying Date Filter: >= {min_date}")
            query_text += f" AND LastModifiedTime>={min_date}"

        files_list = []
        current_offset = 0
        page_size = 500  # Default to 500 as requested

        # If no folder path provided, we only want most recent 500, so we just run one page
        run_once = False
        if not folder_path:
            run_once = True

        while True:
            search_request = SearchRequest(
                entity_types=[EntityType.DriveItem],
                query=SearchQuery(query_string=query_text),
                from_=current_offset,
                size=page_size,
                region=self.region,
                sort_properties=[
                    SortProperty(name="LastModifiedTime", is_descending=True)
                ],
            )

            print(f"  [INFO] Sending search query (offset={current_offset})...")

            request_body = QueryPostRequestBody(requests=[search_request])
            result = await self.client.search.query.post(body=request_body)

            if not result.value or not result.value[0].hits_containers:
                print("  [INFO] No results returned.")
                break

            hits_container = result.value[0].hits_containers[0]
            if not hits_container.hits:
                print("  [INFO] No hits found.")
                break

            current_hits = hits_container.hits
            num_hits = len(current_hits)
            print(f"  [INFO] Found {num_hits} items in this page.")

            for hit in current_hits:
                resource = hit.resource
                item_id = resource.id
                item_name = resource.name

                # Construct relative path using web_url as requested
                readable_path = "Unknown"

                # Try web_url stripping first
                if resource.web_url and self.drive_web_url:
                    full_url = urllib.parse.unquote(resource.web_url)
                    base_url = urllib.parse.unquote(self.drive_web_url)

                    if full_url.startswith(base_url):
                        readable_path = full_url[len(base_url) :]
                        if readable_path.startswith("/"):
                            readable_path = readable_path[1:]

                # Fallback to parent_reference if web_url parsing failed
                if (
                    readable_path == "Unknown"
                    and resource.parent_reference
                    and resource.parent_reference.path
                ):
                    raw_folder = resource.parent_reference.path.split("root:")[-1]
                    if raw_folder.startswith("/"):
                        raw_folder = raw_folder[1:]
                    full_path_encoded = os.path.join(raw_folder, item_name)
                    readable_path = urllib.parse.unquote(full_path_encoded)

                if readable_path in exclude_paths:
                    continue

                files_list.append(
                    {
                        "item_id": item_id,
                        "name": item_name,
                        "relative_path": readable_path,
                        "size": resource.size if hasattr(resource, "size") else 0,
                        "modified_date": resource.last_modified_date_time.isoformat()
                        if resource.last_modified_date_time
                        else None,
                    }
                )

            if run_once:
                print("  [INFO] Stopping after first page (no folder specified).")
                break

            if num_hits < page_size:
                print("  [INFO] Reached end of results.")
                break

            current_offset += page_size

        print(f"  [FOUND] {len(files_list)} PDF files in SharePoint via Search")
        return files_list

    async def list_all_sharepoint_files(self, exclude_paths=None):
        """
        List all PDF files from SharePoint without downloading.
        Returns list of dicts with: item_id, name, relative_path, size, modified_date
        """
        if exclude_paths is None:
            exclude_paths = set()

        if not self.drive_id:
            await self.initialize_drive()

        print(
            f"[{datetime.now()}] Listing all PDF files from SharePoint Drive {self.drive_id}..."
        )

        files_list = []

        # Use delta API to traverse all files (no delta link, fresh listing)
        request = (
            self.client.drives.by_drive_id(self.drive_id)
            .items.by_drive_item_id("root")
            .delta
        )

        response = await request.get()

        limit = int(os.getenv("SHAREPOINT_LIMIT", "10"))

        while True:
            if response.value:
                for item in response.value:
                    # Skip deleted items and directories
                    if item.deleted is not None or not item.file:
                        continue

                    # Filter for PDF files only
                    if not item.name.lower().endswith(".pdf"):
                        continue

                    # Build relative path (same logic as process_item)
                    parent_path = ""
                    if item.parent_reference and item.parent_reference.path:
                        path_part = item.parent_reference.path.split("root:")[-1]
                        if path_part.startswith("/"):
                            path_part = path_part[1:]
                        parent_path = urllib.parse.unquote(path_part)

                    relative_path = os.path.join(parent_path, item.name)

                    # Check if file is already synced (in DB)
                    if relative_path in exclude_paths:
                        continue

                    # Collect file metadata
                    files_list.append(
                        {
                            "item_id": item.id,
                            "name": item.name,
                            "relative_path": relative_path,
                            "size": item.size if hasattr(item, "size") else 0,
                            "modified_date": item.last_modified_date_time.isoformat()
                            if hasattr(item, "last_modified_date_time")
                            and item.last_modified_date_time
                            else None,
                        }
                    )
                    self.processed_count += 1
                    if self.processed_count >= limit:
                        print(
                            f"  [LIMIT REACHED] Processed {self.processed_count} files (Limit: {limit}). Stopping listing."
                        )
                        return files_list

            # Pagination handling
            if response.odata_next_link:
                response = (
                    await self.client.drives.by_drive_id(self.drive_id)
                    .items.by_drive_item_id("root")
                    .delta.with_url(response.odata_next_link)
                    .get()
                )
            else:
                break

        print(f"  [FOUND] {len(files_list)} PDF files in SharePoint")
        return files_list

    async def sync_single_file(self, item_id: str):
        """
        Sync a single file by SharePoint item_id.
        Downloads, ingests, and processes the file.
        Returns: {success: bool, message: str, doc_id: str (if success)}
        """
        if not self.drive_id:
            await self.initialize_drive()

        print(f"[{datetime.now()}] Syncing single file with item_id: {item_id}...")

        try:
            # Fetch item metadata from SharePoint
            item = (
                await self.client.drives.by_drive_id(self.drive_id)
                .items.by_drive_item_id(item_id)
                .get()
            )

            # Verify it's a file and not deleted
            if not item.file or item.deleted is not None:
                return {
                    "success": False,
                    "message": "Item is not a valid file or has been deleted",
                }

            # Verify it's a PDF
            if not item.name.lower().endswith(".pdf"):
                return {"success": False, "message": "Only PDF files are supported"}

            # Build relative path
            parent_path = ""
            if item.parent_reference and item.parent_reference.path:
                path_part = item.parent_reference.path.split("root:")[-1]
                if path_part.startswith("/"):
                    path_part = path_part[1:]
                parent_path = urllib.parse.unquote(path_part)

            relative_path = os.path.join(parent_path, item.name)

            # Download the file
            success = await self.download_file(item.id, relative_path)

            if not success:
                return {
                    "success": False,
                    "message": f"Failed to download file: {item.name}",
                }

            # Update file map
            self.state["fileMap"][item.id] = relative_path

            # Ingest the file
            full_local_path = os.path.join(LOCAL_SYNC_DIR, relative_path)
            self.ingest_file(Path(full_local_path), relative_path)

            print(f"  [SUCCESS] Single file sync completed for {item.name}")
            return {
                "success": True,
                "message": f"Successfully synced {item.name}",
                "file_name": item.name,
            }

        except Exception as e:
            print(f"  [ERROR] Failed to sync file {item_id}: {e}")
            return {"success": False, "message": f"Error syncing file: {str(e)}"}

    async def sync_batch(self, item_ids: list[str]):
        """
        Sync a batch of files by their item_ids.
        """
        if not self.drive_id:
            await self.initialize_drive()

        print(f"[{datetime.now()}] Starting batch sync for {len(item_ids)} items...")

        results = []
        for item_id in item_ids:
            try:
                res = await self.sync_single_file(item_id)
                results.append(res)
            except Exception as e:
                print(f"  [BATCH ERROR] Failed to sync item {item_id}: {e}")
                results.append({"success": False, "message": str(e)})

        print(f"[{datetime.now()}] Batch sync complete.")
        return results

    async def download_file(self, item_id, relative_path):
        full_local_path = os.path.join(LOCAL_SYNC_DIR, relative_path)
        os.makedirs(os.path.dirname(full_local_path), exist_ok=True)

        print(f"  [DOWNLOADING] {relative_path}...")
        try:
            # Use the dynamically fetched self.drive_id
            stream = (
                await self.client.drives.by_drive_id(self.drive_id)
                .items.by_drive_item_id(item_id)
                .content.get()
            )

            with open(full_local_path, "wb") as f:
                f.write(stream)
            print(f"  [SUCCESS] Saved {relative_path}")
            return True
        except Exception as e:
            print(f"  [ERROR] Failed to download {relative_path}: {e}")
            return False

    async def delete_local_file(self, item_id):
        if item_id in self.state["fileMap"]:
            relative_path = self.state["fileMap"][item_id]
            full_path = os.path.join(LOCAL_SYNC_DIR, relative_path)

            # DB Deletion Logic: Find doc by source_uri and delete everywhere
            db = SessionLocal()
            try:
                from models.base import Document
                from services.deletion_service import delete_document_everywhere

                # Find document by source_uri (relative_path) and tenant
                doc = (
                    db.query(Document)
                    .filter(
                        Document.source_uri == relative_path,
                        Document.tenant_id == self.target_tenant_id,
                    )
                    .first()
                )

                if doc:
                    print(
                        f"  [DELETING] Found document {doc.doc_id} for {relative_path}, deleting everywhere..."
                    )
                    delete_document_everywhere(db, doc.doc_id, self.target_tenant_id)
                    db.commit()
                else:
                    print(f"  [DELETE SKIPPED] No document found for {relative_path}")

            except Exception as e:
                db.rollback()
                print(
                    f"  [DELETE ERROR] Failed to delete document for {relative_path}: {e}"
                )
            finally:
                db.close()

            # Local File Cleanup
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                    print(f"  [DELETED] Local file removed: {relative_path}")
                    try:
                        os.removedirs(os.path.dirname(full_path))
                    except OSError:
                        pass
                except Exception as e:
                    print(f"  [ERROR] Could not delete {relative_path}: {e}")

            del self.state["fileMap"][item_id]

    async def sync(self):
        if not self.drive_id:
            await self.initialize_drive()

        print(f"[{datetime.now()}] Starting Sync on Drive {self.drive_id}...")

        if self.state["deltaLink"]:
            print("  Using existing Delta Token...")
            request = (
                self.client.drives.by_drive_id(self.drive_id)
                .items.by_drive_item_id("root")
                .delta.with_url(self.state["deltaLink"])
            )
        else:
            print("  Performing initial full sync...")
            request = (
                self.client.drives.by_drive_id(self.drive_id)
                .items.by_drive_item_id("root")
                .delta
            )

        response = await request.get()

        while True:
            if response.value:
                for item in response.value:
                    # Soft limit via env var (no hardcoding)
                    limit = int(os.getenv("SHAREPOINT_LIMIT", "100"))
                    if self.processed_count >= limit:
                        print(
                            f"  [LIMIT REACHED] Processed {self.processed_count} files (Limit: {limit}). Stopping sync."
                        )
                        return
                    await self.process_item(item)

            if response.odata_next_link:
                response = (
                    await self.client.drives.by_drive_id(self.drive_id)
                    .items.by_drive_item_id("root")
                    .delta.with_url(response.odata_next_link)
                    .get()
                )
            elif response.odata_delta_link:
                self.save_state(delta_link=response.odata_delta_link)
                print("  Sync complete. State saved.")
                break
            else:
                break

    async def process_item(self, item):
        if item.deleted is not None:
            await self.delete_local_file(item.id)
            return

        if item.file:
            # if not item.name.lower().endswith('.pdf'):
            #    return

            parent_path = ""
            if item.parent_reference and item.parent_reference.path:
                path_part = item.parent_reference.path.split("root:")[-1]
                if path_part.startswith("/"):
                    path_part = path_part[1:]
                parent_path = urllib.parse.unquote(path_part)

            relative_path = os.path.join(parent_path, item.name)

            success = await self.download_file(item.id, relative_path)

            if success:
                self.state["fileMap"][item.id] = relative_path
                # Ingest the downloaded file
                full_local_path = os.path.join(LOCAL_SYNC_DIR, relative_path)
                self.ingest_file(Path(full_local_path), relative_path)
                self.processed_count += 1

    def ingest_file(self, file_path: Path, relative_path: str):
        """Ingest a single file into the system."""
        print(f"  [INGEST] Processing {file_path.name}...")

        try:
            # Removed Whitelist: Allow all supported files
            # if "Acceptable" not in file_path.name: ...

            # Read file content and calculate hash
            with open(file_path, "rb") as f:
                content = f.read()

            sha256_hash = hashlib.sha256(content).hexdigest()
            stat = file_path.stat()

            # Create DB session
            db = SessionLocal()
            try:
                # Call internal processing method
                success, message, doc_data, _, chain_sig = (
                    self.batch_service._process_single_file(
                        file_path=file_path,
                        tenant_id=self.target_tenant_id,
                        db=db,
                        content=content,
                        sha256_hash=sha256_hash,
                        stat=stat,
                        source_uri=relative_path,  # Use relative path as source_uri
                    )
                )

                if success:
                    db.commit()
                    print(f"  [INGEST SUCCESS] {message}")

                    # Dispatch processing tasks (ASYNC INGESTION RESTORED)
                    if chain_sig:
                        chain_sig.apply_async()
                        print(
                            f"  [TASK] Dispatched processing tasks for {doc_data.get('doc_id')}"
                        )

                    # Removed Forced Ready Status
                    # Document will update to 'ready' via Worker pipeline
                else:
                    db.rollback()
                    print(f"  [INGEST SKIPPED/FAILED] {message}")

            except Exception as e:
                db.rollback()
                print(f"  [INGEST ERROR] Database error: {e}")
                raise
            finally:
                db.close()

        except Exception as e:
            print(f"  [INGEST ERROR] Failed to ingest {file_path}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sync SharePoint documents and ingest them."
    )
    parser.add_argument(
        "--tenant-id", required=True, help="Target Tenant UUID for ingestion"
    )
    parser.add_argument(
        "--full-resync",
        action="store_true",
        help="Clear sync state to force full re-sync",
    )

    args = parser.parse_args()

    syncer = SharePointSync(target_tenant_id=args.tenant_id)

    if args.full_resync:
        print(f"  [FULL RESYNC] Clearing state file {syncer.state_file}...")
        if os.path.exists(syncer.state_file):
            os.remove(syncer.state_file)
            # Re-load empty state
            syncer.state = syncer.load_state()

    asyncio.run(syncer.sync())
