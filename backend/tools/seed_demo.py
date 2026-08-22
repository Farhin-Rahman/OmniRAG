#!/usr/bin/env python3
"""
Demo seeder: creates a demo tenant, admin user, and ingests a sample document.

Usage:
    python -m tools.seed_demo

What it does:
    1. Creates tenant "Demo Organization" (idempotent)
    2. Creates admin user demo@omnirag.ai / Demo1234! (idempotent)
    3. Downloads a sample PDF and queues it for RAG ingestion
    4. Prints credentials and tenant ID for the Automation Pipeline page
"""

import hashlib
import sys
import logging
from uuid import uuid4

import requests

from services.db.postgres_service import SessionLocal
from models.base import Tenant, User
from utils.auth import hash_password

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

DEMO_EMAIL = "demo@omnirag.ai"
DEMO_PASSWORD = "Demo1234!"
DEMO_TENANT_NAME = "Demo Organization"
SAMPLE_PDF_URL = "https://www.w3.org/WAI/WCAG21/wcag21.pdf"
SAMPLE_PDF_NAME = "WCAG 2.1 Accessibility Guidelines.pdf"


def seed():
    db = SessionLocal()
    try:
        # 1. Tenant
        tenant = db.query(Tenant).filter_by(name=DEMO_TENANT_NAME).first()
        if not tenant:
            tenant = Tenant(tenant_id=uuid4(), name=DEMO_TENANT_NAME, is_active=1)
            db.add(tenant)
            db.flush()
            print(f"  Created tenant: {DEMO_TENANT_NAME}")
        else:
            print(f"  Tenant already exists: {DEMO_TENANT_NAME}")

        # 2. Admin user
        user = db.query(User).filter_by(email=DEMO_EMAIL).first()
        if not user:
            user = User(
                user_id=uuid4(),
                email=DEMO_EMAIL,
                password_hash=hash_password(DEMO_PASSWORD),
                full_name="Demo Admin",
                role="admin",
                tenant_id=tenant.tenant_id,
                is_active=1,
            )
            db.add(user)
            print(f"  Created user: {DEMO_EMAIL}")
        else:
            print(f"  User already exists: {DEMO_EMAIL}")

        db.commit()

        print()
        print("=" * 50)
        print("  Demo credentials")
        print("=" * 50)
        print(f"  Email:     {DEMO_EMAIL}")
        print(f"  Password:  {DEMO_PASSWORD}")
        print(f"  Tenant ID: {tenant.tenant_id}")
        print("=" * 50)

        # 3. Ingest sample document via webhook (non-blocking)
        tenant_id = str(tenant.tenant_id)
        print()
        print("  Queuing sample document for ingestion…")
        try:
            resp = requests.post(
                "http://localhost:8081/api/webhooks/ingest-url",
                json={"url": SAMPLE_PDF_URL, "doc_name": SAMPLE_PDF_NAME, "tenant_id": tenant_id},
                timeout=10,
            )
            if resp.status_code in (200, 202):
                data = resp.json()
                print(f"  Document queued: {data.get('doc_name')} (id={data.get('doc_id')})")
            elif resp.status_code == 401:
                print("  Set WEBHOOK_SECRET= (empty) in .env to allow unauthenticated webhook calls in dev.")
            else:
                print(f"  Ingest returned {resp.status_code}: {resp.text[:120]}")
        except requests.exceptions.ConnectionError:
            print("  Backend not running — start docker-compose first, then re-run to ingest the sample doc.")

        print()
        print("  Open the app: http://localhost:5173")
        print("  Automation page: http://localhost:5173/automation")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding demo data…")
    seed()
