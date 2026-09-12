"""
MCP server for campaign moderation — Trust & Safety.

Exposes the same moderation logic the HTTP API uses (moderation/actions.py,
moderation/rules.py, db/recommendations.py) as MCP tools, so an actual
agent (Claude Desktop, or any MCP client) can review a campaign: check
deterministic rules, reason about it, and record a recommendation. A human
with the TrustAndSafetyAdmin role still makes the real decision — the
agent never has approve/reject/escalate authority without that check
passing, verified here the same way api/deps.py verifies it for HTTP
requests, just via an explicit reviewer_email parameter instead of a
Firebase bearer token (MCP's transport doesn't carry one).

Run directly on the host, not inside Docker — Claude Desktop spawns MCP
servers as local subprocesses over stdio, which doesn't fit a container.
Since backend/ is bind-mounted into the running Docker backend, this reads
and writes the exact same SQLite file (data/audit.db) the containerized
API uses, so recommendations/decisions made through either path show up
in the same audit trail and the same agreement-rate metric.

Usage (e.g. in Claude Desktop's config):
    {
      "mcpServers": {
        "omnirag-moderation": {
          "command": "<path to>/.venv/Scripts/python.exe",
          "args": ["<path to>/backend/mcp_server.py"]
        }
      }
    }
"""

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

# Run from anywhere and still resolve backend-relative imports/paths
# (gcp-service-account.json lives in backend/, hence chdir there).
sys.path.insert(0, _BACKEND_DIR)
os.chdir(_BACKEND_DIR)

# db/audit.py and db/recommendations.py default to the relative path
# "data/audit.db", which only resolves correctly *inside* the Docker
# container — there, docker-compose bind-mounts ./data (repo root) onto
# /app/backend/data, so that relative path lands on the repo-root data/
# folder. Run natively on the host (as this script must, since Claude
# Desktop spawns MCP servers as local subprocesses over stdio — that
# doesn't fit a container) and the same relative path resolves to
# backend/data instead, a real but disconnected local folder. Point both
# explicitly at the actual shared file so this script and the running
# Docker backend read/write the exact same audit trail.
_SHARED_DB_PATH = os.path.join(_REPO_ROOT, "data", "audit.db")
os.environ.setdefault("AUDIT_DB_PATH", _SHARED_DB_PATH)
os.environ.setdefault("RECOMMENDATIONS_DB_PATH", _SHARED_DB_PATH)

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from mcp.server import MCPServer

from db.recommendations import compute_agreement_rate, record_recommendation
from moderation.actions import do_approve, do_escalate, do_reject
from moderation.rules import CampaignSubmission, check_campaign_rules, has_hard_block

SERVICE_ACCOUNT_PATH = "gcp-service-account.json"
REQUIRED_ROLE = "TrustAndSafetyAdmin"

cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
firebase_admin.initialize_app(cred)

mcp = MCPServer("omnirag-moderation")


def _verify_reviewer(reviewer_email: str) -> str:
    """Look up the reviewer by email and confirm they hold the
    TrustAndSafetyAdmin claim — the same check api/deps.py does for HTTP
    requests, adapted for MCP's parameter-based identity instead of a
    bearer token. Returns the reviewer's uid, or raises."""
    try:
        user = firebase_auth.get_user_by_email(reviewer_email)
    except firebase_auth.UserNotFoundError:
        raise ValueError(f"No Firebase user found for {reviewer_email}")

    roles = (user.custom_claims or {}).get("roles", [])
    if REQUIRED_ROLE not in roles:
        raise PermissionError(
            f"{reviewer_email} does not have the {REQUIRED_ROLE} role (has: {roles})"
        )
    return user.uid


@mcp.tool()
async def check_campaign_rules_tool(
    title: str, description: str, target_amount: float
) -> dict:
    """Run deterministic policy checks on a campaign submission — no AI judgment,
    just fixed rules (banned phrases, description length, target amount bounds).

    Args:
        title: Campaign title
        description: Campaign description
        target_amount: Fundraising target amount
    """
    campaign = CampaignSubmission(
        title=title, description=description, target_amount=target_amount
    )
    violations = check_campaign_rules(campaign)
    return {
        "violations": [v.model_dump() for v in violations],
        "hard_block": has_hard_block(violations),
    }


@mcp.tool()
async def record_campaign_recommendation(
    campaign_id: str,
    recommended_action: str,
    risk_score: float,
    risk_category: str,
    rationale: str,
    title: str = "",
    description: str = "",
    target_amount: float = 0.0,
) -> dict:
    """Record your (the agent's) moderation recommendation for a campaign, after
    reviewing it. This does NOT take any action — a human reviewer still has to
    approve, reject, or escalate separately. recommended_action must be one of
    APPROVE, REJECT, ESCALATE.

    Args:
        campaign_id: Identifier of the campaign being reviewed
        recommended_action: One of APPROVE, REJECT, ESCALATE
        risk_score: Your assessed risk, 0.0 (no concern) to 1.0 (high concern)
        risk_category: Short label for the type of concern, e.g. "low", "fraud_indicators", "policy_violation"
        rationale: Your reasoning, in a sentence or two
        title: Campaign title, so it shows up in the human reviewer's queue (optional)
        description: Campaign description, likewise (optional)
        target_amount: Campaign target amount, likewise (optional)
    """
    row_id = record_recommendation(
        campaign_id=campaign_id,
        source="mcp-agent",
        recommended_action=recommended_action,
        risk_score=risk_score,
        risk_category=risk_category,
        rationale=rationale,
        title=title or None,
        description=description or None,
        target_amount=target_amount or None,
    )
    return {"recorded": True, "recommendation_id": row_id}


@mcp.tool()
async def approve_campaign(campaign_id: str, reviewer_email: str) -> dict:
    """Approve a campaign. Requires the reviewer to hold the TrustAndSafetyAdmin
    role — this is a real, human-authoritative action, not something the agent
    can do on its own initiative without a named, authorized reviewer.

    Args:
        campaign_id: Identifier of the campaign to approve
        reviewer_email: Email of the human reviewer authorizing this action
    """
    uid = _verify_reviewer(reviewer_email)
    return do_approve(campaign_id, uid, reviewer_email)


@mcp.tool()
async def reject_campaign(
    campaign_id: str, reviewer_email: str, reason_code: str
) -> dict:
    """Reject a campaign. Requires the reviewer to hold the TrustAndSafetyAdmin role.

    Args:
        campaign_id: Identifier of the campaign to reject
        reviewer_email: Email of the human reviewer authorizing this action
        reason_code: Short code explaining the rejection
    """
    uid = _verify_reviewer(reviewer_email)
    return do_reject(campaign_id, uid, reviewer_email, reason_code)


@mcp.tool()
async def escalate_campaign(
    campaign_id: str, reviewer_email: str, fraud_flag: bool, notes: str
) -> dict:
    """Escalate a campaign for deeper review. Requires the reviewer to hold the
    TrustAndSafetyAdmin role.

    Args:
        campaign_id: Identifier of the campaign to escalate
        reviewer_email: Email of the human reviewer authorizing this action
        fraud_flag: Whether fraud is suspected
        notes: Free-text context for whoever picks up the escalation
    """
    uid = _verify_reviewer(reviewer_email)
    return do_escalate(campaign_id, uid, reviewer_email, fraud_flag, notes)


@mcp.tool()
async def get_agreement_rate() -> dict:
    """Get the eval metric: of campaigns with both an AI recommendation and a
    human final decision, what fraction agreed? Computed from real usage."""
    return compute_agreement_rate()


if __name__ == "__main__":
    mcp.run(transport="stdio")
