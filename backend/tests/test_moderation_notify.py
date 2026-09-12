"""
Unit tests for Slack moderation alerts.

No real network calls — mocks httpx.post and asserts the no-op/failure
paths never raise.
"""

from unittest.mock import patch

from moderation.notify import notify_slack


class TestNotifySlack:
    def test_noop_when_unconfigured(self, monkeypatch):
        import config.settings as settings_module

        monkeypatch.setattr(settings_module.settings, "slack_webhook_url", "")

        with patch("moderation.notify.httpx.post") as mock_post:
            notify_slack("test message")
            mock_post.assert_not_called()

    def test_posts_when_configured(self, monkeypatch):
        import config.settings as settings_module

        monkeypatch.setattr(
            settings_module.settings,
            "slack_webhook_url",
            "https://hooks.slack.com/services/fake",
        )

        with patch("moderation.notify.httpx.post") as mock_post:
            notify_slack("campaign-1 was hard-blocked")
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            assert args[0] == "https://hooks.slack.com/services/fake"
            assert kwargs["json"] == {"text": "campaign-1 was hard-blocked"}

    def test_never_raises_on_network_failure(self, monkeypatch):
        import config.settings as settings_module

        monkeypatch.setattr(
            settings_module.settings,
            "slack_webhook_url",
            "https://hooks.slack.com/services/fake",
        )

        with patch(
            "moderation.notify.httpx.post", side_effect=Exception("network error")
        ):
            notify_slack(
                "this should not raise"
            )  # no assertion needed — success is not raising
