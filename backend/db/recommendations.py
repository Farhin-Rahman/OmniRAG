"""
AI recommendation log for campaign moderation.

Sibling to db/audit.py — same lightweight raw-sqlite, append-only pattern.
Separate table (not the audit ledger itself) because these are what an AI
reviewer *suggested*, not what a human actually decided; keeping them apart
is what makes the agreement-rate eval metric (recommendations vs. ledger,
joined by campaign_id) meaningful rather than circular. Append-only for the
same reason as the ledger: a recommendation that could be edited after the
fact would undermine that metric's integrity.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("RECOMMENDATIONS_DB_PATH", "data/audit.db")

VALID_ACTIONS = ("APPROVE", "REJECT", "ESCALATE")

# ai_recommendations uses present-tense verbs (APPROVE), audit_ledger uses
# past-tense (APPROVED) — this is just that naming reconciled for the join.
_ACTION_MAP = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "ESCALATE": "ESCALATED"}


@contextmanager
def _connect():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_recommendations_db() -> None:
    """Create the ai_recommendations table and its append-only guards if missing."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                source TEXT NOT NULL,
                risk_score REAL,
                risk_category TEXT,
                rationale TEXT,
                recommended_action TEXT NOT NULL CHECK (recommended_action IN ('APPROVE', 'REJECT', 'ESCALATE')),
                timestamp TEXT NOT NULL
            )
            """
        )
        # Added after the initial release: the reviewer UI needs to show
        # what the campaign actually says, not just a risk score. Nullable
        # + a guarded ALTER (not a fresh CREATE) so it migrates an existing
        # append-only table in place without touching its rows.
        for column in ("title TEXT", "description TEXT", "target_amount REAL"):
            try:
                conn.execute(f"ALTER TABLE ai_recommendations ADD COLUMN {column}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" not in str(e):
                    raise
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS ai_recommendations_no_update
            BEFORE UPDATE ON ai_recommendations
            BEGIN
                SELECT RAISE(ABORT, 'ai_recommendations is append-only: updates are not allowed');
            END
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS ai_recommendations_no_delete
            BEFORE DELETE ON ai_recommendations
            BEGIN
                SELECT RAISE(ABORT, 'ai_recommendations is append-only: deletes are not allowed');
            END
            """
        )
    logger.info(f"AI recommendations log ready at {DB_PATH}")


def record_recommendation(
    campaign_id: str,
    source: str,
    recommended_action: str,
    risk_score: Optional[float] = None,
    risk_category: Optional[str] = None,
    rationale: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    target_amount: Optional[float] = None,
) -> int:
    """Insert one AI recommendation. Returns the new row id."""
    if recommended_action not in VALID_ACTIONS:
        raise ValueError(
            f"Invalid recommended_action '{recommended_action}', must be one of {VALID_ACTIONS}"
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ai_recommendations
                (campaign_id, source, risk_score, risk_category, rationale, recommended_action, timestamp, title, description, target_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign_id,
                source,
                risk_score,
                risk_category,
                rationale,
                recommended_action,
                timestamp,
                title,
                description,
                target_amount,
            ),
        )
        row_id = cursor.lastrowid

    logger.info(
        f"AI recommendation: {recommended_action} campaign={campaign_id} "
        f"source={source} risk={risk_score} id={row_id}"
    )
    return row_id


def get_pending_queue() -> list[dict]:
    """Campaigns with an AI recommendation but no human decision yet —
    the reviewer's queue. A campaign drops off once any audit_ledger row
    exists for it (the ledger is append-only, so one row means a human
    has decided). Oldest first, so nothing sits unreviewed indefinitely."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT r.campaign_id, r.source, r.risk_score, r.risk_category,
                   r.rationale, r.recommended_action, r.timestamp,
                   r.title, r.description, r.target_amount
            FROM ai_recommendations r
            WHERE r.id = (
                SELECT MAX(id) FROM ai_recommendations r2 WHERE r2.campaign_id = r.campaign_id
            )
            AND NOT EXISTS (
                SELECT 1 FROM audit_ledger a WHERE a.campaign_id = r.campaign_id
            )
            ORDER BY r.timestamp ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def compute_agreement_rate() -> dict:
    """The actual eval metric: for every campaign with both an AI
    recommendation and a human final decision, do they match? Uses the
    most recent recommendation and most recent ledger action per campaign,
    in case either was recorded more than once. Computed from real usage,
    not a synthetic benchmark."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT r.campaign_id, r.recommended_action, a.action
            FROM ai_recommendations r
            JOIN audit_ledger a ON a.campaign_id = r.campaign_id
            WHERE r.id = (
                SELECT MAX(id) FROM ai_recommendations r2 WHERE r2.campaign_id = r.campaign_id
            )
            AND a.id = (
                SELECT MAX(id) FROM audit_ledger a2 WHERE a2.campaign_id = a.campaign_id
            )
            """
        ).fetchall()

    total = len(rows)
    if total == 0:
        return {"total_compared": 0, "agreed": 0, "agreement_rate": None}

    agreed = sum(
        1
        for _, rec_action, human_action in rows
        if _ACTION_MAP.get(rec_action) == human_action
    )
    return {
        "total_compared": total,
        "agreed": agreed,
        "agreement_rate": round(agreed / total, 4),
    }
