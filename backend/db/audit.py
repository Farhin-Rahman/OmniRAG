"""
Append-only audit ledger for Trust & Safety moderation actions.

Deliberately a separate, lightweight SQLite database (raw sqlite3, not the
main app's Postgres/SQLAlchemy models) — a moderation audit trail should be
simple and dependency-light. "Append-only" is enforced at the database
level via triggers that abort any UPDATE/DELETE outright, not merely by
convention of which functions this module happens to expose.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("AUDIT_DB_PATH", "data/audit.db")

VALID_ACTIONS = ("APPROVED", "REJECTED", "ESCALATED")


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_audit_db() -> None:
    """Create the audit_ledger table and its append-only guards if missing."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('APPROVED', 'REJECTED', 'ESCALATED')),
                reviewer_uid TEXT NOT NULL,
                reason_code TEXT,
                document_hash TEXT,
                timestamp TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS audit_ledger_no_update
            BEFORE UPDATE ON audit_ledger
            BEGIN
                SELECT RAISE(ABORT, 'audit_ledger is append-only: updates are not allowed');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS audit_ledger_no_delete
            BEFORE DELETE ON audit_ledger
            BEGIN
                SELECT RAISE(ABORT, 'audit_ledger is append-only: deletes are not allowed');
            END
            """
        )
    logger.info(f"Audit ledger ready at {DB_PATH}")


def append_audit_record(
    campaign_id: str,
    action: str,
    reviewer_uid: str,
    reason_code: Optional[str] = None,
    document_hash: Optional[str] = None,
) -> int:
    """Insert one moderation decision into the ledger. Returns the new row id."""
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}', must be one of {VALID_ACTIONS}")

    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO audit_ledger
                (campaign_id, action, reviewer_uid, reason_code, document_hash, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (campaign_id, action, reviewer_uid, reason_code, document_hash, timestamp),
        )
        row_id = cursor.lastrowid

    logger.info(
        f"Audit ledger: {action} campaign={campaign_id} by={reviewer_uid} id={row_id}"
    )
    return row_id
