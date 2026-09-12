"""Deterministic eval — the rule-engine slice of the golden set, run in CI.

The labelled campaigns in moderation/eval/golden_set.py are scored two ways:

  - here, deterministically, on every commit: does the rule engine's
    hard-block verdict match the label? No LLM, no API key, no cost, so it
    belongs in CI.
  - offline (moderation/eval/run_eval.py): the full pipeline, LLM
    included, measured against the same labels — costs real API calls, so
    it runs on demand, not on every push.

This file is the "deterministic evals wired into CI" half of that split.
Same dataset, two bars.
"""

import pytest

from moderation.eval.golden_set import GOLDEN_SET
from moderation.rules import CampaignSubmission, check_campaign_rules, has_hard_block


@pytest.mark.parametrize("case", GOLDEN_SET, ids=lambda c: c.id)
def test_hard_block_verdict_matches_label(case):
    """Every golden-set case's deterministic hard-block outcome must match
    its label. A regression here means the rule engine changed behaviour
    on a known input."""
    violations = check_campaign_rules(
        CampaignSubmission(
            title=case.title,
            description=case.description,
            target_amount=case.target_amount,
        )
    )
    actual = has_hard_block(violations)
    assert actual is case.expect_hard_block, (
        f"{case.id}: rule engine hard_block={actual}, "
        f"golden set expects {case.expect_hard_block} — {case.note}"
    )


def test_golden_set_covers_both_outcomes():
    """The deterministic eval is only meaningful if the set exercises both
    a hard block and a clean pass."""
    labels = {c.expect_hard_block for c in GOLDEN_SET}
    assert labels == {True, False}, (
        "golden set must contain both hard-block and non-block cases"
    )
