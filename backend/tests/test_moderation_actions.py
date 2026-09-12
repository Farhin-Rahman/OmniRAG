"""
Unit tests for moderation action logic (approve/reject/escalate) and the
append-only audit ledger they write to.

Uses a temp SQLite file per test via monkeypatching db.audit.DB_PATH — does
not touch the real data/audit.db.
"""

import sqlite3

import pytest

import db.audit as audit_module
from moderation.actions import do_approve, do_escalate, do_reject


@pytest.fixture
def temp_audit_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_audit.db")
    monkeypatch.setattr(audit_module, "DB_PATH", db_path)
    audit_module.init_audit_db()
    return db_path


class TestActions:
    def test_approve_writes_ledger_row(self, temp_audit_db):
        result = do_approve("campaign-1", "uid-1", "reviewer@example.com")
        assert result["status"] == "approved"

        conn = sqlite3.connect(temp_audit_db)
        row = conn.execute(
            "SELECT campaign_id, action, reviewer_uid FROM audit_ledger WHERE campaign_id = 'campaign-1'"
        ).fetchone()
        assert row == ("campaign-1", "APPROVED", "uid-1")

    def test_reject_stores_reason_code(self, temp_audit_db):
        do_reject("campaign-2", "uid-1", "reviewer@example.com", "INCOMPLETE_DOCS")

        conn = sqlite3.connect(temp_audit_db)
        row = conn.execute(
            "SELECT action, reason_code FROM audit_ledger WHERE campaign_id = 'campaign-2'"
        ).fetchone()
        assert row == ("REJECTED", "INCOMPLETE_DOCS")

    def test_escalate_encodes_fraud_flag_and_notes(self, temp_audit_db):
        do_escalate(
            "campaign-3",
            "uid-1",
            "reviewer@example.com",
            True,
            "duplicate bank details",
        )

        conn = sqlite3.connect(temp_audit_db)
        row = conn.execute(
            "SELECT action, reason_code FROM audit_ledger WHERE campaign_id = 'campaign-3'"
        ).fetchone()
        assert row[0] == "ESCALATED"
        assert "fraud_flag=True" in row[1]
        assert "duplicate bank details" in row[1]


class TestAppendOnly:
    def test_update_is_blocked(self, temp_audit_db):
        do_approve("campaign-4", "uid-1", "reviewer@example.com")
        conn = sqlite3.connect(temp_audit_db)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE audit_ledger SET action = 'REJECTED' WHERE campaign_id = 'campaign-4'"
            )
            conn.commit()

    def test_delete_is_blocked(self, temp_audit_db):
        do_approve("campaign-5", "uid-1", "reviewer@example.com")
        conn = sqlite3.connect(temp_audit_db)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM audit_ledger WHERE campaign_id = 'campaign-5'")
            conn.commit()
