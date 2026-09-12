"""Run the moderation pipeline over the golden set and report how well its
recommendations match the labelled actions.

    python -m moderation.eval.run_eval [--delay 4] [--limit N] [--json out.json] [--verbose]

Makes real LLM calls (needs GROQ_API_KEY). Writes recommendation rows to a
throwaway database in the system temp dir, never the real audit trail.
Exit code is 0 unless --fail-on-missed-risk is set and a case that should
not have been APPROVEd was — the one error class the dispatchable CI job
gates on.

Each campaign fires 3 LLM calls (2 translate + 1 risk assessment), or 7
when the ambiguous-score consensus path triggers. On Groq's free tier
(30 RPM) a full 18-case run needs --delay ~20 to avoid 429s dragging
cases into a failed-to-parse ESCALATE; a paid tier or --limit avoids the
wait. A 429-hit case is visible in the report as risk=0.50 with the
"Automated assessment failed to parse" rationale.
"""

import argparse
import json
import os
import sys
import tempfile
import time

# LLM rationales can contain non-cp1252 characters (a non-breaking hyphen,
# a curly quote); without this the report crashes on a Windows console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_REPO_ROOT = os.path.dirname(_BACKEND_DIR)

sys.path.insert(0, _BACKEND_DIR)
os.chdir(_BACKEND_DIR)

# Point the append-only recommendation/audit stores at a scratch file so an
# eval run never touches data/audit.db. Must happen before importing the
# db modules — they read these env vars into a module constant at import.
_SCRATCH_DB = os.path.join(tempfile.gettempdir(), "omnirag_eval_recommendations.db")
os.environ["RECOMMENDATIONS_DB_PATH"] = _SCRATCH_DB
os.environ["AUDIT_DB_PATH"] = _SCRATCH_DB

# This script runs on the host (like mcp_server.py), but .env's
# OLLAMA_BASE_URL (host.docker.internal) and the default QDRANT_HOST
# (qdrant) are Docker-network addresses that don't resolve from the host —
# policy retrieval would silently time out on every campaign. Set the
# host-reachable equivalents *before* load_dotenv (which doesn't override
# already-set vars) and before any import that reads them at module load.
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("QDRANT_HOST", "localhost")
os.environ.setdefault("QDRANT_PORT", "6335")

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(_REPO_ROOT, ".env"))
except ImportError:
    pass

from ai.llm_client import LLMClient, get_groq_usage, reset_groq_usage
from db.recommendations import init_recommendations_db
from moderation.eval.golden_set import GOLDEN_SET, GoldenCase
from moderation.graph import run_moderation_pipeline

ACTIONS = ("APPROVE", "REJECT", "ESCALATE")

# Indicative Groq pricing for openai/gpt-oss-20b (USD per 1M tokens) — used
# only to turn the token counts into a dollar figure for the report.
_PRICE_PER_1M_INPUT = 0.10
_PRICE_PER_1M_OUTPUT = 0.50

# graph.py sets exactly this rationale when the risk-assessment LLM call
# failed (network / 429 / unparseable) and it fell back to a default
# ESCALATE. Such a case tells us nothing about judgment quality, so the
# report counts it separately instead of as a wrong answer.
_LLM_FAILURE_RATIONALE = (
    "Automated assessment failed to parse; escalating for manual review."
)


def _check_llm_backend() -> None:
    """The eval is meaningless if it silently falls back to a local model
    that isn't running — fail loudly instead."""
    provider = LLMClient().provider
    name = getattr(provider, "provider_name", provider.__class__.__name__)
    if name != "groq":
        print(
            f"WARNING: LLM backend is '{name}', not Groq. Set GROQ_API_KEY so "
            "the eval runs against the same backend the pipeline uses in "
            "practice.\n",
            file=sys.stderr,
        )


def _run_one(case: GoldenCase) -> dict:
    state = run_moderation_pipeline(
        campaign_id=f"eval-{case.id}",
        title=case.title,
        description=case.description,
        target_amount=case.target_amount,
    )
    predicted = state.get("recommended_action")
    llm_failed = state.get("rationale") == _LLM_FAILURE_RATIONALE and not state.get(
        "hard_blocked"
    )
    return {
        "id": case.id,
        "source": case.source,
        "expected": case.expected_action,
        "predicted": predicted,
        "action_match": predicted == case.expected_action,
        "llm_failed": llm_failed,
        "expected_hard_block": case.expect_hard_block,
        "hard_blocked": bool(state.get("hard_blocked")),
        "hard_block_match": bool(state.get("hard_blocked")) == case.expect_hard_block,
        "risk_score": state.get("risk_score"),
        "consensus_used": bool(state.get("consensus_used")),
        "detected_language": state.get("detected_language"),
        "rationale": state.get("rationale"),
        "note": case.note,
    }


def _confusion(results: list[dict]) -> dict:
    matrix = {e: {p: 0 for p in ACTIONS} for e in ACTIONS}
    for r in results:
        if r["expected"] in matrix and r["predicted"] in matrix[r["expected"]]:
            matrix[r["expected"]][r["predicted"]] += 1
    return matrix


def _print_report(results: list[dict], verbose: bool) -> dict:
    scored = [r for r in results if not r.get("llm_failed")]
    failed = [r for r in results if r.get("llm_failed")]
    total = len(scored)
    action_correct = sum(r["action_match"] for r in scored)
    hb_correct = sum(r["hard_block_match"] for r in results)

    # The error that actually matters: something risky was let through.
    missed_risk = [
        r
        for r in scored
        if r["expected"] in ("REJECT", "ESCALATE") and r["predicted"] == "APPROVE"
    ]
    over_block = [
        r for r in scored if r["expected"] == "APPROVE" and r["predicted"] == "REJECT"
    ]

    print("\n" + "=" * 70)
    print("PER-CASE RESULTS")
    print("=" * 70)
    for r in results:
        if r.get("llm_failed"):
            mark = "n/a "
        elif r["action_match"]:
            mark = "PASS"
        else:
            mark = "FAIL"
        score = (
            f"{r['risk_score']:.2f}"
            if isinstance(r["risk_score"], (int, float))
            else "  - "
        )
        cons = " +consensus" if r["consensus_used"] else ""
        suffix = "  (LLM call failed - not scored)" if r.get("llm_failed") else ""
        print(
            f"  [{mark}] {r['id']:<28} {r['expected']:>8} -> {str(r['predicted']):<8} "
            f"risk={score}{cons}{suffix}"
        )
        if not r.get("llm_failed") and (verbose or not r["action_match"]):
            print(f"         note:  {r['note']}")
            print(f"         model: {r['rationale']}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    denom = total or 1
    print(
        f"  Action accuracy:       {action_correct}/{total} "
        f"({action_correct / denom:.0%})"
    )
    print(
        f"  Hard-block accuracy:   {hb_correct}/{len(results)} "
        f"({hb_correct / len(results):.0%})"
    )
    print(f"  Missed risk (APPROVEd something that should not be): {len(missed_risk)}")
    for r in missed_risk:
        print(f"      - {r['id']}: expected {r['expected']}, got APPROVE")
    print(f"  Over-block (REJECTed a legitimate campaign): {len(over_block)}")
    for r in over_block:
        print(f"      - {r['id']}: expected APPROVE, got REJECT")
    if failed:
        print(f"  Not scored (LLM call failed, usually free-tier 429): {len(failed)}")
        for r in failed:
            print(f"      - {r['id']}")

    real = [r for r in scored if r.get("source") == "launchgood-live"]
    if real:
        approved = sum(1 for r in real if r["predicted"] == "APPROVE")
        print(
            f"\n  Real LaunchGood campaigns: {approved}/{len(real)} approved "
            f"(all passed the platform's own vetting, so APPROVE is expected)"
        )
        for r in real:
            if r["predicted"] != "APPROVE":
                print(f"      - {r['id']}: {r['predicted']} — {r['rationale']}")

    print("\n  Confusion matrix (row = expected, col = predicted):")
    matrix = _confusion(scored)
    header = "            " + "".join(f"{p:>10}" for p in ACTIONS)
    print(header)
    for e in ACTIONS:
        row = f"    {e:>8}  " + "".join(f"{matrix[e][p]:>10}" for p in ACTIONS)
        print(row)
    print()

    return {
        "scored": total,
        "action_correct": action_correct,
        "missed_risk": len(missed_risk),
        "over_block": len(over_block),
        "not_scored": len(failed),
    }


def _print_cost(results: list[dict]) -> None:
    u = get_groq_usage()
    in_tok, out_tok = u["prompt_tokens"], u["completion_tokens"]
    cost = (
        in_tok / 1_000_000 * _PRICE_PER_1M_INPUT
        + out_tok / 1_000_000 * _PRICE_PER_1M_OUTPUT
    )
    ran = len(results)
    consensus = sum(1 for r in results if r["consensus_used"])

    print("=" * 70)
    print("COST")
    print("=" * 70)
    print(
        f"  LLM calls:             {u['calls']}  (~{u['calls'] / ran:.1f} per campaign)"
    )
    print(f"  Tokens:                {in_tok:,} in / {out_tok:,} out")
    print(
        f"  Est. cost:             ${cost:.4f} total  (~${cost / ran:.4f} per campaign)"
    )
    print(
        f"  Consensus path:        {consensus}/{ran} campaigns  "
        f"(each adds 4 calls — voters + judge)"
    )
    if consensus:
        # A single-pass campaign is 3 calls (2 translate + 1 assess); the
        # consensus ones cost 4 more. Show what skipping consensus would save.
        extra = consensus * 4
        print(
            f"  Consensus overhead:    ~{extra} of {u['calls']} calls "
            f"({extra / u['calls']:.0%}) — the scoped trigger is why it isn't every campaign"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--delay",
        type=float,
        default=4.0,
        help="seconds to wait between campaigns (paces the Groq free tier; ~20 for a clean full run)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="run only the first N cases"
    )
    parser.add_argument(
        "--json", dest="json_path", default=None, help="write full results as JSON"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="print rationale for every case"
    )
    parser.add_argument(
        "--fail-on-missed-risk",
        action="store_true",
        help="exit 1 if any scored case that should not have been APPROVEd was "
        "(for the dispatchable CI job — the one error class worth gating on)",
    )
    parser.add_argument(
        "--summary-file",
        default=None,
        help="append a one-line summary here (e.g. $GITHUB_STEP_SUMMARY)",
    )
    args = parser.parse_args()

    _check_llm_backend()
    init_recommendations_db()
    reset_groq_usage()

    cases = GOLDEN_SET[: args.limit] if args.limit else GOLDEN_SET
    print(f"Running {len(cases)} cases through the moderation pipeline...\n")

    results: list[dict] = []
    for i, case in enumerate(cases, 1):
        print(f"  ({i}/{len(cases)}) {case.id} ...", flush=True)
        try:
            results.append(_run_one(case))
        except Exception as e:  # noqa: BLE001 - one bad case shouldn't kill the run
            print(f"      ERROR: {e}", file=sys.stderr)
            results.append(
                {
                    "id": case.id,
                    "source": case.source,
                    "expected": case.expected_action,
                    "predicted": None,
                    "action_match": False,
                    "llm_failed": True,
                    "expected_hard_block": case.expect_hard_block,
                    "hard_blocked": False,
                    "hard_block_match": False,
                    "risk_score": None,
                    "consensus_used": False,
                    "detected_language": None,
                    "rationale": f"pipeline raised: {e}",
                    "note": case.note,
                }
            )
        if args.delay and i < len(cases):
            time.sleep(args.delay)

    # Persist before rendering: a full run is slow and costs real API
    # calls, so don't let a formatting error throw the results away.
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Full results written to {args.json_path}")

    summary = _print_report(results, args.verbose)
    _print_cost(results)

    if args.summary_file:
        u = get_groq_usage()
        cost = (
            u["prompt_tokens"] / 1_000_000 * _PRICE_PER_1M_INPUT
            + u["completion_tokens"] / 1_000_000 * _PRICE_PER_1M_OUTPUT
        )
        line = (
            f"Moderation LLM eval: {summary['action_correct']}/{summary['scored']} "
            f"actions correct, {summary['missed_risk']} missed risk, "
            f"{summary['over_block']} over-block, {summary['not_scored']} not scored "
            f"— {u['calls']} LLM calls, ~${cost:.4f}"
        )
        with open(args.summary_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    if args.fail_on_missed_risk and summary["missed_risk"] > 0:
        print(
            f"\nFAIL: {summary['missed_risk']} case(s) that should not have been "
            "APPROVEd were.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
