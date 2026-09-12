"""Unit tests for db/recommendations.py — specifically get_pending_queue(),
the query behind the reviewer's queue: a campaign should appear once it
has an AI recommendation, and disappear once a human has decided."""

import db.audit as audit_module
import db.recommendations as rec_module


class TestGetPendingQueue:
    def _setup(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        monkeypatch.setattr(rec_module, "DB_PATH", db_path)
        monkeypatch.setattr(audit_module, "DB_PATH", db_path)
        rec_module.init_recommendations_db()
        audit_module.init_audit_db()

    def test_campaign_with_recommendation_and_no_decision_is_pending(
        self, tmp_path, monkeypatch
    ):
        self._setup(tmp_path, monkeypatch)
        rec_module.record_recommendation(
            campaign_id="camp-1",
            source="langgraph-auto",
            recommended_action="ESCALATE",
            risk_score=0.5,
            risk_category="uncertain",
            rationale="Needs a human look.",
            title="Help my family",
            description="A vague appeal with no specifics.",
            target_amount=5000,
        )

        queue = rec_module.get_pending_queue()

        assert len(queue) == 1
        assert queue[0]["campaign_id"] == "camp-1"
        assert queue[0]["title"] == "Help my family"
        assert queue[0]["target_amount"] == 5000

    def test_campaign_with_a_human_decision_is_not_pending(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        rec_module.record_recommendation(
            campaign_id="camp-2",
            source="langgraph-auto",
            recommended_action="APPROVE",
            risk_score=0.1,
            title="Clean campaign",
        )
        audit_module.append_audit_record(
            campaign_id="camp-2",
            action="APPROVED",
            reviewer_uid="uid-1",
            reason_code=None,
            document_hash="hash",
        )

        assert rec_module.get_pending_queue() == []

    def test_only_the_latest_recommendation_per_campaign_is_used(
        self, tmp_path, monkeypatch
    ):
        self._setup(tmp_path, monkeypatch)
        rec_module.record_recommendation(
            campaign_id="camp-3",
            source="langgraph-auto",
            recommended_action="ESCALATE",
            risk_score=0.5,
            title="First pass",
        )
        rec_module.record_recommendation(
            campaign_id="camp-3",
            source="mcp-agent",
            recommended_action="REJECT",
            risk_score=0.9,
            title="Second, more informed pass",
        )

        queue = rec_module.get_pending_queue()

        assert len(queue) == 1
        assert queue[0]["title"] == "Second, more informed pass"
        assert queue[0]["recommended_action"] == "REJECT"

    def test_empty_queue_when_nothing_recorded(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        assert rec_module.get_pending_queue() == []
