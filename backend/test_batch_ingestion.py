"""
Simple test script for batch ingestion functionality.
This can be run to verify the batch processing endpoint works correctly.
"""

import os
import sys
import logging

# Add the backend directory to the Python path
sys.path.insert(0, os.path.abspath("."))

from config.logging import setup_logging
from services.batch_ingestion_service import get_batch_ingestion_service

# Setup centralized logging
setup_logging()


def test_batch_service():
    """Test the batch ingestion service functionality."""
    logger = logging.getLogger(__name__)
    logger.info("Testing Batch Ingestion Service")
    logger.info("=" * 50)

    # Get the service
    batch_service = get_batch_ingestion_service()

    # Test directory creation
    logger.info(f"Batch input directory: {batch_service.batch_input_dir}")
    logger.info(f"Tracking file: {batch_service.tracking_file}")
    logger.info(f"Supported extensions: {batch_service.supported_extensions}")

    # Ensure directories exist
    batch_service._ensure_directories()

    # Check if directories were created
    if batch_service.batch_input_dir.exists():
        logger.info(f"✅ Batch input directory exists: {batch_service.batch_input_dir}")
    else:
        logger.error(
            f"❌ Batch input directory not found: {batch_service.batch_input_dir}"
        )

    # Test scanning for files (should be empty initially)
    files = batch_service._scan_batch_directory()
    logger.info(f"📁 Found {len(files)} files in batch directory")

    if len(files) == 0:
        logger.info("💡 To test file processing, add some PDF or DOCX files to:")
        logger.info(f"   {batch_service.batch_input_dir.absolute()}")
        logger.info("   Then you can test the batch endpoint with:")
        logger.info("   POST /ingest/batch")
    else:
        logger.info("📋 Files found:")
        for file in files:
            logger.info(f"   - {file.name}")

    # Test tracking file operations
    logger.info("🔍 Testing tracking file operations...")

    # Load existing tracking data
    processed_files = batch_service._load_processed_files()
    logger.info(f"Currently tracked files: {len(processed_files)}")

    if processed_files:
        logger.info("📝 Tracked files:")
        for filename, metadata in processed_files.items():
            logger.info(
                f"   - {filename}: processed at {metadata.get('processed_at', 'unknown')}"
            )

    logger.info("✅ Batch ingestion service test completed!")
    logger.info("📋 Next steps:")
    logger.info("   1. Add PDF/DOCX files to the batch input directory")
    logger.info("   2. Make a POST request to /ingest/batch with proper headers:")
    logger.info("      - Authorization: Bearer <token>")
    logger.info("      - Authorization: Bearer <your-jwt>")
    logger.info("   3. Check the response for processing results")


if __name__ == "__main__":
    test_batch_service()
