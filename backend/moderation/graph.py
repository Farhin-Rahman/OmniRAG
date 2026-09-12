"""
Automatic campaign moderation pipeline — LangGraph.

Runs the moment a campaign is submitted, with no human driving it turn by
turn — that's what the MCP server (mcp_server.py) + an interactive agent
like Claude Desktop is for, when a human wants to dig into a specific
case collaboratively. This is the "fast lane": every submission gets
translated, rule-checked, and risk-assessed automatically, so a reviewer
opens their queue to a recommendation already sitting there rather than a
blank campaign.

translate -> rules -> risk_assessment -> record, linear, no cycles —
matches the scope of the problem: nothing here needs branching or retries.
"""

import json
import logging
from typing import List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from ai.llm_client import LLMClient
from config.settings import settings
from db.recommendations import record_recommendation
from moderation.json_extract import extract_json_object
from moderation.notify import notify_slack
from moderation.policy_retrieval import retrieve_policy_context
from moderation.rules import CampaignSubmission, check_campaign_rules, has_hard_block
from moderation.translate import translate_to_english

logger = logging.getLogger(__name__)

RISK_ASSESSMENT_PROMPT = """You are a trust & safety reviewer for a crowdfunding platform. Assess this campaign for risk. Respond with ONLY compact JSON, no prose, no markdown fences.

Schema: {{"risk_score": <0.0-1.0>, "risk_category": "<short label>", "recommended_action": "APPROVE"|"REJECT"|"ESCALATE", "rationale": "<one or two sentences>"}}

Actions:
- APPROVE only when the campaign is BOTH clearly legitimate AND verifiable — a specific purpose, a named person/organization/institution, and either an itemized use of funds or a concrete deliverable. "Sounds sympathetic" is not enough.
- ESCALATE when the purpose is plausible but the campaign gives no way to verify it (no names, no itemized costs, no documentation offered, only a vague story), or when the target amount doesn't match the stated purpose. A sympathetic cause with zero specifics is an ESCALATE, not an APPROVE — unverifiable medical, personal-hardship, and "fund my idea" appeals are a common fraud pattern.
- REJECT for clear fraud signals: financial-scheme / guaranteed-return language, pressure to pay off-platform, impersonation, gift-card asks.

Score 0.0-0.3 for clearly-legitimate-and-verifiable, 0.3-0.7 for plausible-but-unverifiable or amount-mismatch (these get a second look), 0.7-1.0 for clear fraud signals.

Relevant LaunchGood policy, retrieved for this specific campaign — cite it by name in your rationale when it applies:
{policy_context}

Campaign title: {title}
Campaign description: {description}
Target amount: {target_amount}

JSON:"""

# Only reached when a single risk-assessment pass itself wasn't confident
# (score landed in this ambiguous middle band) — real extra cost (3 voter
# calls + 1 judge call), so it's deliberately not run on every campaign.
CONSENSUS_SCORE_RANGE = (0.3, 0.7)

JUDGE_PROMPT = """You are a senior trust & safety reviewer. Three independent reviewers assessed the same campaign and reached different conclusions. Read their assessments and give the final call. Respond with ONLY compact JSON, no prose, no markdown fences.

Schema: {{"risk_score": <0.0-1.0>, "risk_category": "<short label>", "recommended_action": "APPROVE"|"REJECT"|"ESCALATE", "rationale": "<one or two sentences, referencing the disagreement if relevant>"}}

Relevant LaunchGood policy, retrieved for this specific campaign:
{policy_context}

Campaign title: {title}
Campaign description: {description}
Target amount: {target_amount}

Reviewer 1: {voter_1}
Reviewer 2: {voter_2}
Reviewer 3: {voter_3}

JSON:"""


class ModerationState(TypedDict):
    campaign_id: str
    title: str
    description: str
    target_amount: float
    detected_language: Optional[str]
    translated_title: Optional[str]
    translated_description: Optional[str]
    rule_violations: List[dict]
    hard_blocked: bool
    policy_context: Optional[str]
    risk_score: Optional[float]
    risk_category: Optional[str]
    recommended_action: Optional[str]
    rationale: Optional[str]
    consensus_used: bool


def _translate_node(state: ModerationState) -> ModerationState:
    title_result = translate_to_english(state["title"])
    desc_result = translate_to_english(state["description"])
    state["detected_language"] = desc_result["detected_language"]
    state["translated_title"] = title_result["translated_text"]
    state["translated_description"] = desc_result["translated_text"]
    return state


def _rules_node(state: ModerationState) -> ModerationState:
    campaign = CampaignSubmission(
        title=state["translated_title"],
        description=state["translated_description"],
        target_amount=state["target_amount"],
    )
    violations = check_campaign_rules(campaign)
    state["rule_violations"] = [v.model_dump() for v in violations]
    state["hard_blocked"] = has_hard_block(violations)
    return state


def _call_llm_json(llm: LLMClient, prompt: str, temperature: float) -> Optional[dict]:
    """Call the LLM and parse a JSON object from its response. Returns
    None on any failure (network, malformed JSON) rather than raising —
    callers decide how to degrade."""
    try:
        # 2000, not a few hundred: MODERATION_LLM_MODEL is a reasoning model
        # (gpt-oss), which spends completion tokens on hidden reasoning
        # before the JSON. A tight budget gets consumed entirely by
        # reasoning and returns an empty string (finish_reason "length").
        raw = llm.generate(prompt, temperature=temperature, max_tokens=2000)
        return extract_json_object(raw)
    except Exception as e:
        logger.warning(f"LLM JSON call failed: {e}")
        return None


def _run_consensus_judge(
    title: str, description: str, target_amount: float, policy_context: str
) -> Optional[dict]:
    """3 independent voters (temperature 0.5, for genuine variation) plus
    1 judge that reviews all three and gives the final call — a real
    LLM-as-judge pattern, not a disguised majority vote. Only called for
    single-pass scores that landed in CONSENSUS_SCORE_RANGE. Reuses the
    single policy retrieval already done for this campaign rather than
    querying again per voter."""
    llm = LLMClient(model=settings.moderation_llm_model)
    voter_prompt = RISK_ASSESSMENT_PROMPT.format(
        title=title,
        description=description,
        target_amount=target_amount,
        policy_context=policy_context,
    )

    voters = [
        v
        for v in (_call_llm_json(llm, voter_prompt, temperature=0.5) for _ in range(3))
        if v
    ]
    if len(voters) < 2:
        # Not enough voters succeeded to make a judge call meaningful.
        return None

    judge_prompt = JUDGE_PROMPT.format(
        title=title,
        description=description,
        target_amount=target_amount,
        policy_context=policy_context,
        voter_1=json.dumps(voters[0]),
        voter_2=json.dumps(voters[1]),
        voter_3=json.dumps(voters[2]) if len(voters) > 2 else "N/A",
    )
    return _call_llm_json(llm, judge_prompt, temperature=0.0)


def _risk_assessment_node(state: ModerationState) -> ModerationState:
    state["consensus_used"] = False

    if state["hard_blocked"]:
        # A deterministic rule already caught something disqualifying —
        # don't spend an LLM call (or a retrieval) second-guessing a hard
        # block.
        state["policy_context"] = None
        block_reasons = "; ".join(
            v["detail"] for v in state["rule_violations"] if v["severity"] == "block"
        )
        state["risk_score"] = 1.0
        state["risk_category"] = "rule_violation"
        state["recommended_action"] = "REJECT"
        state["rationale"] = f"Blocked by deterministic policy rule: {block_reasons}"
        notify_slack(
            f":no_entry: Campaign `{state['campaign_id']}` hard-blocked: {block_reasons}"
        )
        return state

    policy_context = (
        retrieve_policy_context(
            f"{state['translated_title']}. {state['translated_description']}"
        )
        or "(no specific policy passage retrieved)"
    )
    state["policy_context"] = policy_context

    llm = LLMClient(model=settings.moderation_llm_model)
    prompt = RISK_ASSESSMENT_PROMPT.format(
        title=state["translated_title"],
        description=state["translated_description"],
        target_amount=state["target_amount"],
        policy_context=policy_context,
    )
    result = _call_llm_json(llm, prompt, temperature=0.0) or {}

    state["risk_score"] = result.get("risk_score", 0.5)
    state["risk_category"] = result.get("risk_category", "unknown")
    state["recommended_action"] = result.get("recommended_action", "ESCALATE")
    state["rationale"] = result.get(
        "rationale",
        "Automated assessment failed to parse; escalating for manual review.",
    )

    low, high = CONSENSUS_SCORE_RANGE
    if low <= state["risk_score"] <= high:
        consensus_result = _run_consensus_judge(
            state["translated_title"],
            state["translated_description"],
            state["target_amount"],
            policy_context,
        )
        if consensus_result:
            state["consensus_used"] = True
            state["risk_score"] = consensus_result.get(
                "risk_score", state["risk_score"]
            )
            state["risk_category"] = consensus_result.get(
                "risk_category", state["risk_category"]
            )
            state["recommended_action"] = consensus_result.get(
                "recommended_action", state["recommended_action"]
            )
            state["rationale"] = consensus_result.get("rationale", state["rationale"])

    return state


def _record_node(state: ModerationState) -> ModerationState:
    record_recommendation(
        campaign_id=state["campaign_id"],
        source="langgraph-auto-consensus"
        if state["consensus_used"]
        else "langgraph-auto",
        recommended_action=state["recommended_action"],
        risk_score=state["risk_score"],
        risk_category=state["risk_category"],
        rationale=state["rationale"],
        title=state["translated_title"],
        description=state["translated_description"],
        target_amount=state["target_amount"],
    )
    return state


def build_moderation_graph():
    graph = StateGraph(ModerationState)
    graph.add_node("translate", _translate_node)
    graph.add_node("rules", _rules_node)
    graph.add_node("risk_assessment", _risk_assessment_node)
    graph.add_node("record", _record_node)

    graph.set_entry_point("translate")
    graph.add_edge("translate", "rules")
    graph.add_edge("rules", "risk_assessment")
    graph.add_edge("risk_assessment", "record")
    graph.add_edge("record", END)

    return graph.compile()


_compiled_graph = None


def run_moderation_pipeline(
    campaign_id: str, title: str, description: str, target_amount: float
) -> dict:
    """Run the full automatic pipeline for one campaign submission."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_moderation_graph()

    initial_state: ModerationState = {
        "campaign_id": campaign_id,
        "title": title,
        "description": description,
        "target_amount": target_amount,
        "detected_language": None,
        "translated_title": None,
        "translated_description": None,
        "rule_violations": [],
        "hard_blocked": False,
        "policy_context": None,
        "risk_score": None,
        "risk_category": None,
        "recommended_action": None,
        "rationale": None,
        "consensus_used": False,
    }
    final_state = _compiled_graph.invoke(initial_state)
    logger.info(
        f"Moderation pipeline: campaign={campaign_id} action={final_state['recommended_action']} "
        f"risk={final_state['risk_score']} lang={final_state['detected_language']}"
    )
    return final_state
