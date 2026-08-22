#!/usr/bin/env python3
"""
CLI tool to refresh ACL payloads in Qdrant for existing documents.

Usage:
    python -m tools.refresh_acl --tenant-id <UUID> [--all]
    python -m tools.refresh_acl --doc-id <UUID>

Examples:
    # Refresh all documents in a specific tenant
    python -m tools.refresh_acl --tenant-id 123e4567-e89b-12d3-a456-426614174000 --all

    # Refresh a specific document
    python -m tools.refresh_acl --doc-id 123e4567-e89b-12d3-a456-426614174000
"""

import argparse
import sys
import logging
from uuid import UUID

from sqlalchemy.orm import Session

from services.db.postgres_service import SessionLocal
from services.acl_service import refresh_doc_acl_payload
from models.base import Document

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def refresh_tenant(tenant_id: UUID, db: Session):
    """Refresh ACLs for all documents in a tenant."""
    logger.info(f"Scanning documents for tenant {tenant_id}...")

    docs = db.query(Document).filter(Document.tenant_id == tenant_id).all()
    logger.info(f"Found {len(docs)} documents.")

    success_count = 0
    fail_count = 0

    for i, doc in enumerate(docs):
        logger.info(f"[{i + 1}/{len(docs)}] Refreshing {doc.doc_id}...")
        result = refresh_doc_acl_payload(doc.doc_id, db)

        if result["success"]:
            success_count += 1
        else:
            fail_count += 1
            logger.error(f"Failed: {result.get('error')}")

    logger.info(f"Done. Success: {success_count}, Failed: {fail_count}")


def refresh_document(doc_id: UUID, db: Session):
    """Refresh ACL for a single document."""
    logger.info(f"Refreshing document {doc_id}...")
    result = refresh_doc_acl_payload(doc_id, db)

    if result["success"]:
        logger.info(f"Success: {result}")
    else:
        logger.error(f"Failed: {result}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Refresh Qdrant ACL payloads")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant-id", type=str, help="Tenant uuid to refresh")
    group.add_argument("--doc-id", type=str, help="Document uuid to refresh")

    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all docs in tenant (required with --tenant-id)",
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.doc_id:
            refresh_document(UUID(args.doc_id), db)
        elif args.tenant_id:
            if not args.all:
                parser.error("--all is required when specifying --tenant-id")
            refresh_tenant(UUID(args.tenant_id), db)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
