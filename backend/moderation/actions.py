"""
Shared campaign moderation actions.

The actual decision logic — called by both the HTTP routes
(routes/campaigns.py) and the MCP server (mcp_server.py), so there is
exactly one implementation of "what happens when a campaign is approved,"
not two copies that can drift apart.
"""

from db.audit import append_audit_record
from moderation.notify import notify_slack


def do_approve(campaign_id: str, reviewer_uid: str, reviewer_label: str) -> dict:
    append_audit_record(
        campaign_id=campaign_id, action="APPROVED", reviewer_uid=reviewer_uid
    )
    return {
        "campaign_id": campaign_id,
        "status": "approved",
        "approved_by": reviewer_label,
    }


def do_reject(
    campaign_id: str, reviewer_uid: str, reviewer_label: str, reason_code: str
) -> dict:
    append_audit_record(
        campaign_id=campaign_id,
        action="REJECTED",
        reviewer_uid=reviewer_uid,
        reason_code=reason_code,
    )
    return {
        "campaign_id": campaign_id,
        "status": "rejected",
        "reason_code": reason_code,
        "rejected_by": reviewer_label,
    }


def do_escalate(
    campaign_id: str,
    reviewer_uid: str,
    reviewer_label: str,
    fraud_flag: bool,
    notes: str,
) -> dict:
    # The ledger's reason_code is the only free-text column in its fixed
    # schema — fraud_flag and notes are both encoded into it.
    reason_code = f"fraud_flag={fraud_flag}|notes={notes}"
    append_audit_record(
        campaign_id=campaign_id,
        action="ESCALATED",
        reviewer_uid=reviewer_uid,
        reason_code=reason_code,
    )
    notify_slack(
        f":rotating_light: Campaign `{campaign_id}` escalated by {reviewer_label} "
        f"(fraud_flag={fraud_flag}): {notes}"
    )
    return {
        "campaign_id": campaign_id,
        "status": "escalated",
        "fraud_flag": fraud_flag,
        "notes": notes,
        "escalated_by": reviewer_label,
    }
