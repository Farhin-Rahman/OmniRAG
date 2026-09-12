"""Tests for the automation intake endpoint (POST /webhooks/campaign-review).

The pipeline itself is covered in test_moderation_graph.py — here the
concern is the HTTP seam: the webhook-secret check, and that the response
is trimmed to what a notification workflow needs.
"""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.webhooks import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

_PIPELINE_RESULT = {
    "campaign_id": "camp-1",
    "recommended_action": "ESCALATE",
    "risk_score": 0.55,
    "risk_category": "uncertain",
    "rationale": "Plausible but underspecified; a human should look.",
    "hard_blocked": False,
    "consensus_used": True,
    "detected_language": "en",
    # fields the endpoint should drop from its response:
    "translated_title": "x",
    "rule_violations": [],
}

_BODY = {
    "campaign_id": "camp-1",
    "title": "Help fund the clinic",
    "description": "A longer description that clears the minimum length rule.",
    "target_amount": 5000,
}


class TestCampaignReviewWebhook:
    def test_returns_trimmed_recommendation(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
        with patch(
            "routes.webhooks.run_moderation_pipeline", return_value=_PIPELINE_RESULT
        ):
            resp = client.post("/webhooks/campaign-review", json=_BODY)
        assert resp.status_code == 200
        data = resp.json()
        assert data == {
            "campaign_id": "camp-1",
            "recommended_action": "ESCALATE",
            "risk_score": 0.55,
            "risk_category": "uncertain",
            "rationale": "Plausible but underspecified; a human should look.",
            "hard_blocked": False,
            "consensus_used": True,
            "detected_language": "en",
        }

    def test_rejects_wrong_secret_when_configured(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
        with patch(
            "routes.webhooks.run_moderation_pipeline", return_value=_PIPELINE_RESULT
        ) as mock_pipeline:
            resp = client.post(
                "/webhooks/campaign-review",
                json=_BODY,
                headers={"X-Webhook-Secret": "wrong"},
            )
        assert resp.status_code == 401
        mock_pipeline.assert_not_called()

    def test_accepts_correct_secret_when_configured(self, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
        with patch(
            "routes.webhooks.run_moderation_pipeline", return_value=_PIPELINE_RESULT
        ):
            resp = client.post(
                "/webhooks/campaign-review",
                json=_BODY,
                headers={"X-Webhook-Secret": "s3cret"},
            )
        assert resp.status_code == 200

    def test_rejects_non_positive_target_amount(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
        resp = client.post(
            "/webhooks/campaign-review", json={**_BODY, "target_amount": 0}
        )
        assert resp.status_code == 422

    def test_generates_campaign_id_when_omitted(self, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
        body = {k: v for k, v in _BODY.items() if k != "campaign_id"}
        with patch(
            "routes.webhooks.run_moderation_pipeline", return_value=_PIPELINE_RESULT
        ) as mock_pipeline:
            resp = client.post("/webhooks/campaign-review", json=body)
        assert resp.status_code == 200
        generated_id = resp.json()["campaign_id"]
        assert generated_id.startswith("camp-")
        # the generated id is what the pipeline was called with
        assert mock_pipeline.call_args.kwargs["campaign_id"] == generated_id
