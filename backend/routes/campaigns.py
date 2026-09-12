"""
Campaign moderation routes — Trust & Safety.

The actual approve/reject/escalate logic lives in moderation/actions.py,
shared with the MCP server (mcp_server.py) so there's one implementation,
not two. This module is the HTTP surface plus the deterministic rule check
and the eval metric.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import AuthenticatedUser, require_roles
from db.recommendations import compute_agreement_rate, get_pending_queue
from moderation.actions import do_approve, do_reject, do_escalate
from moderation.graph import run_moderation_pipeline
from moderation.rules import CampaignSubmission, check_campaign_rules, has_hard_block

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/campaigns", tags=["Campaigns"])


class RejectRequest(BaseModel):
    reason_code: str


class EscalateRequest(BaseModel):
    fraud_flag: bool
    notes: str


@router.post("/{campaign_id}/analyze")
async def analyze_campaign(
    campaign_id: str,
    body: CampaignSubmission,
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    """Deterministic rule check only — no LLM here. This is the layer that
    deliberately doesn't use AI. AI-assisted review happens either
    automatically (POST .../auto-review, a LangGraph pipeline) or
    interactively via the MCP tools, driven by an actual agent."""
    violations = check_campaign_rules(body)
    return {
        "campaign_id": campaign_id,
        "violations": [v.model_dump() for v in violations],
        "hard_block": has_hard_block(violations),
    }


@router.post("/{campaign_id}/auto-review")
async def auto_review_campaign(
    campaign_id: str,
    body: CampaignSubmission,
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    """Run the full automatic pipeline (translate -> rules -> risk
    assessment -> record recommendation) and return the result. This is
    the "fast lane" — no human drives it turn by turn, unlike the
    interactive MCP path. Still records a recommendation only; a human
    makes the actual decision via /approve /reject /escalate."""
    result = run_moderation_pipeline(
        campaign_id=campaign_id,
        title=body.title,
        description=body.description,
        target_amount=body.target_amount,
    )
    return result


@router.get("/queue")
async def review_queue(
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    """The reviewer's queue: campaigns with an AI recommendation and no
    human decision yet. Backs the moderation reviewer UI."""
    return get_pending_queue()


@router.get("/metrics/agreement-rate")
async def agreement_rate(
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    """The eval number: of the campaigns with both an AI recommendation and
    a human final decision, how often did they agree? Computed from real
    usage in the audit ledger + recommendations log, not a benchmark."""
    return compute_agreement_rate()


@router.post("/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: str,
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    result = do_approve(
        campaign_id, current_user.uid, current_user.email or current_user.uid
    )
    logger.info(
        f"Campaign {campaign_id} approved by {current_user.email or current_user.uid}"
    )
    return result


@router.post("/{campaign_id}/reject")
async def reject_campaign(
    campaign_id: str,
    body: RejectRequest,
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    result = do_reject(
        campaign_id,
        current_user.uid,
        current_user.email or current_user.uid,
        body.reason_code,
    )
    logger.info(
        f"Campaign {campaign_id} rejected by {current_user.email or current_user.uid} "
        f"(reason: {body.reason_code})"
    )
    return result


@router.post("/{campaign_id}/escalate")
async def escalate_campaign(
    campaign_id: str,
    body: EscalateRequest,
    current_user: AuthenticatedUser = Depends(require_roles("TrustAndSafetyAdmin")),
):
    result = do_escalate(
        campaign_id,
        current_user.uid,
        current_user.email or current_user.uid,
        body.fraud_flag,
        body.notes,
    )
    logger.info(
        f"Campaign {campaign_id} escalated by {current_user.email or current_user.uid} "
        f"(fraud_flag={body.fraud_flag})"
    )
    return result
