"""
Deterministic rule engine for campaign moderation.

This is deliberately the layer that does NOT use an LLM — cheap, fast,
explainable checks for things that don't need AI judgment. Anything that
isn't caught here goes on to AI-assisted review. Keeping this separate is
the concrete answer to "where does AI stop and something else take over":
some decisions don't need a model at all.
"""

from typing import List

from pydantic import BaseModel, Field

MIN_TARGET_AMOUNT = 1.0
MAX_TARGET_AMOUNT = 10_000_000.0
MIN_DESCRIPTION_LENGTH = 20

# Illustrative, not exhaustive — a real deployment would pull this from a
# maintained policy list, not a hardcoded tuple.
BANNED_KEYWORDS = (
    "guaranteed return",
    "wire me directly",
    "crypto investment",
    "double your money",
    "urgent bank transfer",
)


class CampaignSubmission(BaseModel):
    title: str
    description: str
    target_amount: float = Field(gt=0)


class RuleViolation(BaseModel):
    rule: str
    detail: str
    severity: str  # "block" (hard stop) or "flag" (worth a closer look)


def check_campaign_rules(campaign: CampaignSubmission) -> List[RuleViolation]:
    """Run every deterministic check. An empty result means nothing a fixed
    rule can decide was found — not the same thing as "this is safe"."""
    violations: List[RuleViolation] = []

    text = f"{campaign.title} {campaign.description}".lower()
    for keyword in BANNED_KEYWORDS:
        if keyword in text:
            violations.append(
                RuleViolation(
                    rule="banned_keyword",
                    detail=f"Contains banned phrase: '{keyword}'",
                    severity="block",
                )
            )

    if len(campaign.description.strip()) < MIN_DESCRIPTION_LENGTH:
        violations.append(
            RuleViolation(
                rule="description_too_short",
                detail=f"Description is under {MIN_DESCRIPTION_LENGTH} characters",
                severity="flag",
            )
        )

    if campaign.target_amount > MAX_TARGET_AMOUNT:
        violations.append(
            RuleViolation(
                rule="target_amount_out_of_bounds",
                detail=f"Target amount {campaign.target_amount} exceeds max {MAX_TARGET_AMOUNT}",
                severity="flag",
            )
        )

    return violations


def has_hard_block(violations: List[RuleViolation]) -> bool:
    return any(v.severity == "block" for v in violations)
