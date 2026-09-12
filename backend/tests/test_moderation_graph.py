"""
Unit tests for the automatic LangGraph moderation pipeline.

Mocks LLMClient and retrieve_policy_context — no real network calls, no
GROQ_API_KEY or Qdrant needed. The
point of these tests is the pipeline's wiring and its cost-aware skip
logic (a hard-blocked campaign should never reach the LLM risk-assessment
call), not translation or assessment quality — that's exercised manually
against the real API, not in CI.
"""

import json
import re
from unittest.mock import MagicMock, patch

import db.recommendations as rec_module
from moderation.graph import run_moderation_pipeline


def _fake_generate(prompt, **kwargs):
    """One mock LLM serves both the translation node and the
    risk-assessment node — route based on which prompt was sent.

    For translation, echo back the actual text embedded in the prompt
    (identity "translation", since these tests use English input) rather
    than a fabricated string — otherwise the mock silently discards the
    real campaign content before rules/risk-assessment ever see it.
    """
    if "translate it to English" in prompt:
        match = re.search(r'"""(.*)"""', prompt, re.DOTALL)
        original_text = match.group(1) if match else ""
        return json.dumps({"detected_language": "en", "translated_text": original_text})
    return json.dumps(
        {
            "risk_score": 0.1,
            "risk_category": "low",
            "recommended_action": "APPROVE",
            "rationale": "Looks legitimate.",
        }
    )


class TestModerationPipeline:
    def _make_mock_llm(self):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = _fake_generate
        return mock_llm

    def test_clean_campaign_runs_full_pipeline(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rec_module, "DB_PATH", str(tmp_path / "test.db"))
        rec_module.init_recommendations_db()
        mock_llm = self._make_mock_llm()

        with (
            patch("moderation.translate.LLMClient", return_value=mock_llm),
            patch("moderation.graph.LLMClient", return_value=mock_llm),
            patch("moderation.graph.retrieve_policy_context", return_value=""),
        ):
            result = run_moderation_pipeline(
                campaign_id="test-1",
                title="Clean campaign",
                description="A legitimate campaign description that is long enough.",
                target_amount=5000,
            )

        assert result["hard_blocked"] is False
        assert result["recommended_action"] == "APPROVE"
        assert result["detected_language"] == "en"
        # 2 translation calls (title + description) + 1 risk-assessment call.
        assert mock_llm.generate.call_count == 3

    def test_hard_blocked_campaign_skips_llm_risk_assessment(
        self, tmp_path, monkeypatch
    ):
        """The whole point of checking rules first: a hard-blocked campaign
        should never reach the LLM call — the cost-aware design."""
        monkeypatch.setattr(rec_module, "DB_PATH", str(tmp_path / "test.db"))
        rec_module.init_recommendations_db()
        mock_llm = self._make_mock_llm()

        with (
            patch("moderation.translate.LLMClient", return_value=mock_llm),
            patch("moderation.graph.LLMClient", return_value=mock_llm),
            patch("moderation.graph.retrieve_policy_context", return_value=""),
        ):
            result = run_moderation_pipeline(
                campaign_id="test-2",
                title="Guaranteed return investment",
                description="trust me",
                target_amount=500,
            )

        assert result["hard_blocked"] is True
        assert result["recommended_action"] == "REJECT"
        assert result["risk_category"] == "rule_violation"
        # Only the 2 translation calls happened — no risk-assessment call.
        assert mock_llm.generate.call_count == 2

    def test_recommendation_is_recorded(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        monkeypatch.setattr(rec_module, "DB_PATH", db_path)
        rec_module.init_recommendations_db()
        mock_llm = self._make_mock_llm()

        with (
            patch("moderation.translate.LLMClient", return_value=mock_llm),
            patch("moderation.graph.LLMClient", return_value=mock_llm),
            patch("moderation.graph.retrieve_policy_context", return_value=""),
        ):
            run_moderation_pipeline(
                campaign_id="test-3",
                title="Clean campaign",
                description="A legitimate campaign description that is long enough.",
                target_amount=5000,
            )

        import sqlite3

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT campaign_id, source, recommended_action FROM ai_recommendations WHERE campaign_id = 'test-3'"
        ).fetchone()
        assert row == ("test-3", "langgraph-auto", "APPROVE")


class TestConsensusJudge:
    """The single-pass risk-assessment call and the 3 consensus voters use
    the identical prompt template — so unlike the tests above, these can't
    route mock responses by prompt content. side_effect is an ordered list
    instead, matching the exact call sequence: translate title, translate
    description, single-pass assessment, [voter x3], judge."""

    def test_ambiguous_score_triggers_consensus(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rec_module, "DB_PATH", str(tmp_path / "test.db"))
        rec_module.init_recommendations_db()

        translate_response = json.dumps(
            {
                "detected_language": "en",
                "translated_text": "An ambiguous campaign description.",
            }
        )
        initial_ambiguous = json.dumps(
            {
                "risk_score": 0.5,
                "risk_category": "uncertain",
                "recommended_action": "ESCALATE",
                "rationale": "Not sure.",
            }
        )
        voter_1 = json.dumps(
            {
                "risk_score": 0.2,
                "risk_category": "low",
                "recommended_action": "APPROVE",
                "rationale": "Looks fine.",
            }
        )
        voter_2 = json.dumps(
            {
                "risk_score": 0.8,
                "risk_category": "high",
                "recommended_action": "REJECT",
                "rationale": "Feels risky.",
            }
        )
        voter_3 = json.dumps(
            {
                "risk_score": 0.5,
                "risk_category": "medium",
                "recommended_action": "ESCALATE",
                "rationale": "Unclear.",
            }
        )
        judge_final = json.dumps(
            {
                "risk_score": 0.6,
                "risk_category": "medium",
                "recommended_action": "ESCALATE",
                "rationale": "Reviewers disagreed; escalating for human judgment.",
            }
        )

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            translate_response,
            translate_response,  # title, description
            initial_ambiguous,  # single-pass risk assessment
            voter_1,
            voter_2,
            voter_3,  # consensus voters
            judge_final,  # judge
        ]

        with (
            patch("moderation.translate.LLMClient", return_value=mock_llm),
            patch("moderation.graph.LLMClient", return_value=mock_llm),
            patch("moderation.graph.retrieve_policy_context", return_value=""),
        ):
            result = run_moderation_pipeline(
                campaign_id="test-consensus-1",
                title="Ambiguous campaign",
                description="An ambiguous campaign description.",
                target_amount=5000,
            )

        assert result["consensus_used"] is True
        # Final state reflects the judge's synthesis, not the original
        # ambiguous single-pass result (0.5 / ESCALATE-with-"Not sure.").
        assert result["risk_score"] == 0.6
        assert (
            result["rationale"] == "Reviewers disagreed; escalating for human judgment."
        )
        assert mock_llm.generate.call_count == 7

    def test_confident_score_skips_consensus(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rec_module, "DB_PATH", str(tmp_path / "test.db"))
        rec_module.init_recommendations_db()

        translate_response = json.dumps(
            {"detected_language": "en", "translated_text": "A clearly fine campaign."}
        )
        confident_low = json.dumps(
            {
                "risk_score": 0.05,
                "risk_category": "low",
                "recommended_action": "APPROVE",
                "rationale": "Clearly legitimate.",
            }
        )

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            translate_response,
            translate_response,
            confident_low,
        ]

        with (
            patch("moderation.translate.LLMClient", return_value=mock_llm),
            patch("moderation.graph.LLMClient", return_value=mock_llm),
            patch("moderation.graph.retrieve_policy_context", return_value=""),
        ):
            result = run_moderation_pipeline(
                campaign_id="test-consensus-2",
                title="Clean campaign",
                description="A clearly fine campaign.",
                target_amount=5000,
            )

        assert result["consensus_used"] is False
        assert mock_llm.generate.call_count == 3  # no consensus calls made

    def test_consensus_failure_falls_back_to_original_result(
        self, tmp_path, monkeypatch
    ):
        """If voters can't produce a usable result, keep the original
        single-pass assessment rather than corrupt it with a failure."""
        monkeypatch.setattr(rec_module, "DB_PATH", str(tmp_path / "test.db"))
        rec_module.init_recommendations_db()

        translate_response = json.dumps(
            {"detected_language": "en", "translated_text": "An ambiguous campaign."}
        )
        initial_ambiguous = json.dumps(
            {
                "risk_score": 0.5,
                "risk_category": "uncertain",
                "recommended_action": "ESCALATE",
                "rationale": "Not sure.",
            }
        )

        mock_llm = MagicMock()
        mock_llm.generate.side_effect = [
            translate_response,
            translate_response,
            initial_ambiguous,
            "not valid json",
            "not valid json",
            "not valid json",  # all 3 voters fail to parse
        ]

        with (
            patch("moderation.translate.LLMClient", return_value=mock_llm),
            patch("moderation.graph.LLMClient", return_value=mock_llm),
            patch("moderation.graph.retrieve_policy_context", return_value=""),
        ):
            result = run_moderation_pipeline(
                campaign_id="test-consensus-3",
                title="Ambiguous campaign",
                description="An ambiguous campaign.",
                target_amount=5000,
            )

        assert result["consensus_used"] is False
        assert result["risk_score"] == 0.5
        assert result["recommended_action"] == "ESCALATE"
