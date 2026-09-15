"""
Voice agent booking records.

Sibling to db/audit.py and db/recommendations.py — same lightweight
raw-sqlite pattern. Unlike those two, this isn't append-only: a booking is
a live operational record (might legitimately get rescheduled or
cancelled later), not a compliance/audit trail, so there's no integrity
reason to lock it down the same way.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("BOOKINGS_DB_PATH", "data/audit.db")


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_bookings_db() -> None:
    """Create the bookings table if missing."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_id TEXT,
                service TEXT NOT NULL,
                preferred_day TEXT,
                preferred_time TEXT,
                customer_name TEXT,
                status TEXT NOT NULL DEFAULT 'confirmed',
                created_at TEXT NOT NULL
            )
            """
        )
    logger.info(f"Bookings log ready at {DB_PATH}")


def record_booking(
    service: str,
    call_id: Optional[str] = None,
    preferred_day: Optional[str] = None,
    preferred_time: Optional[str] = None,
    customer_name: Optional[str] = None,
) -> int:
    """Insert one booking. Returns the new row id."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO bookings
                (call_id, service, preferred_day, preferred_time, customer_name, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'confirmed', ?)
            """,
            (call_id, service, preferred_day, preferred_time, customer_name, timestamp),
        )
        row_id = cursor.lastrowid

    logger.info(f"Booking recorded: service={service} call_id={call_id} id={row_id}")
    return row_id


def list_bookings(limit: int = 20) -> list[dict]:
    """Most recent bookings first."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, call_id, service, preferred_day, preferred_time,
                   customer_name, status, created_at
            FROM bookings
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
