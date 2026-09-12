"""
Unit tests for the deterministic campaign moderation rule engine.

No mocking needed — this layer deliberately has no LLM or external calls.
"""

from moderation.rules import (
    CampaignSubmission,
    check_campaign_rules,
    has_hard_block,
)


class TestCleanCampaign:
    def test_no_violations(self):
        campaign = CampaignSubmission(
            title="Water well for Aleppo village",
            description="Building a clean water well to serve 200 families in a rural village.",
            target_amount=15000,
        )
        violations = check_campaign_rules(campaign)
        assert violations == []
        assert has_hard_block(violations) is False


class TestBannedKeywords:
    def test_banned_keyword_is_a_hard_block(self):
        campaign = CampaignSubmission(
            title="Guaranteed return investment opportunity",
            description="This is a legitimate offer with plenty of detail to pass the length check.",
            target_amount=500,
        )
        violations = check_campaign_rules(campaign)
        assert any(
            v.rule == "banned_keyword" and v.severity == "block" for v in violations
        )
        assert has_hard_block(violations) is True

    def test_banned_keyword_detected_case_insensitively(self):
        campaign = CampaignSubmission(
            title="GUARANTEED RETURN on your money",
            description="This is a legitimate offer with plenty of detail to pass the length check.",
            target_amount=500,
        )
        violations = check_campaign_rules(campaign)
        assert any(v.rule == "banned_keyword" for v in violations)

    def test_banned_keyword_in_description_not_just_title(self):
        campaign = CampaignSubmission(
            title="Community fundraiser",
            description="Wire me directly and I'll double your money within a week.",
            target_amount=500,
        )
        violations = check_campaign_rules(campaign)
        assert any(v.rule == "banned_keyword" for v in violations)


class TestDescriptionLength:
    def test_short_description_is_flagged_not_blocked(self):
        campaign = CampaignSubmission(
            title="Community fundraiser",
            description="trust me",
            target_amount=500,
        )
        violations = check_campaign_rules(campaign)
        flag = next(v for v in violations if v.rule == "description_too_short")
        assert flag.severity == "flag"
        # A flag alone shouldn't hard-block on its own.
        assert has_hard_block([flag]) is False


class TestTargetAmountBounds:
    def test_amount_over_max_is_flagged(self):
        campaign = CampaignSubmission(
            title="Community fundraiser",
            description="A perfectly reasonable description that is long enough to pass the check.",
            target_amount=50_000_000,
        )
        violations = check_campaign_rules(campaign)
        assert any(v.rule == "target_amount_out_of_bounds" for v in violations)

    def test_amount_must_be_positive(self):
        # CampaignSubmission itself enforces target_amount > 0 via Pydantic.
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CampaignSubmission(title="x", description="x" * 30, target_amount=0)
