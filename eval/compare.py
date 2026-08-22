"""
Run-to-run comparison for OmniRAG Offline Evaluation.

Loads two MLflow runs, compares metrics, identifies regressions,
and generates a pasteable summary report.

Usage:
    from eval.compare import compare_runs, format_report

    report = compare_runs("run_id_baseline", "run_id_current")
    print(format_report(report))

CLI:
    python -m eval.cli compare --baseline <run_id> --current <run_id>
    python -m eval.cli compare --last 2  # compare two most recent runs
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =========================================================================
# MLflow Helpers
# =========================================================================
def _get_mlflow():
    """Lazy-load MLflow."""
    try:
        import mlflow
        return mlflow
    except ImportError:
        raise ImportError("MLflow required. Install with: pip install mlflow")


def _load_run(mlflow, run_id: str) -> Dict[str, Any]:
    """Load a single MLflow run's data."""
    run = mlflow.get_run(run_id)
    return {
        "run_id": run_id,
        "run_name": run.info.run_name,
        "start_time": datetime.fromtimestamp(run.info.start_time / 1000),
        "end_time": datetime.fromtimestamp(run.info.end_time / 1000) if run.info.end_time else None,
        "status": run.info.status,
        "metrics": dict(run.data.metrics),
        "params": dict(run.data.params),
        "tags": dict(run.data.tags),
    }


def _load_per_example_results(mlflow, run_id: str) -> List[Dict[str, Any]]:
    """Load per-example results JSONL from a run's artifacts."""
    client = mlflow.tracking.MlflowClient()
    artifacts = client.list_artifacts(run_id, "results")

    for artifact in artifacts:
        if artifact.path.endswith(".jsonl") and "eval_results" in artifact.path:
            local_path = client.download_artifacts(run_id, artifact.path)
            results = []
            with open(local_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        results.append(json.loads(line))
            return results
    return []


def _load_failures(mlflow, run_id: str) -> List[Dict[str, Any]]:
    """Load top failures from a run's artifacts."""
    client = mlflow.tracking.MlflowClient()
    try:
        artifacts = client.list_artifacts(run_id, "failures")
    except Exception:
        return []

    for artifact in artifacts:
        if artifact.path.endswith(".jsonl") and "top_failures" in artifact.path:
            local_path = client.download_artifacts(run_id, artifact.path)
            failures = []
            with open(local_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        failures.append(json.loads(line))
            return failures
    return []


def get_latest_runs(
    experiment_name: str = "omnirag_offline_eval",
    n: int = 2,
    tracking_uri: Optional[str] = None,
) -> List[str]:
    """Get the N most recent run IDs from an experiment."""
    mlflow = _get_mlflow()
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    experiment = mlflow.get_experiment_by_name(experiment_name)
    if not experiment:
        raise ValueError(f"Experiment '{experiment_name}' not found")

    runs = mlflow.search_runs(
        experiment_ids=[experiment.experiment_id],
        filter_string="attributes.status = 'FINISHED'",
        order_by=["attributes.start_time DESC"],
        max_results=n,
    )

    if len(runs) < n:
        raise ValueError(
            f"Need {n} completed runs, found {len(runs)} in '{experiment_name}'"
        )

    return list(runs["run_id"])


# =========================================================================
# Metric Comparison
# =========================================================================
# Metrics where higher = better
_HIGHER_IS_BETTER = {
    "mean_doc_recall", "mean_doc_precision", "mean_doc_f1",
    "mean_mrr", "mean_ndcg_at_k",
    "mean_token_f1", "mean_rouge_l",
    "mean_answer_relevance", "mean_faithfulness",
    "citation_rate",
}

# Metrics where lower = better
_LOWER_IS_BETTER = {
    "mean_http_latency_ms", "mean_e2e_ms",
    "mean_embedding_ms", "mean_retrieval_ms", "mean_llm_ms",
    "p50_http_latency_ms", "p90_http_latency_ms", "p95_http_latency_ms",
    "p50_e2e_ms", "p90_e2e_ms", "p95_e2e_ms",
    "p50_embedding_ms", "p90_embedding_ms",
    "p50_retrieval_ms", "p90_retrieval_ms",
    "p50_llm_ms", "p90_llm_ms",
    "cases_with_errors",
}


def _compute_delta(
    baseline_val: Optional[float],
    current_val: Optional[float],
    metric_name: str,
) -> Dict[str, Any]:
    """Compute delta between two metric values."""
    if baseline_val is None or current_val is None:
        return {
            "baseline": baseline_val,
            "current": current_val,
            "delta": None,
            "delta_pct": None,
            "direction": "unknown",
        }

    delta = current_val - baseline_val
    delta_pct = (delta / baseline_val * 100) if baseline_val != 0 else None

    # Determine if change is good or bad
    if metric_name in _HIGHER_IS_BETTER:
        direction = "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
    elif metric_name in _LOWER_IS_BETTER:
        direction = "improved" if delta < 0 else "regressed" if delta > 0 else "unchanged"
    else:
        direction = "changed" if delta != 0 else "unchanged"

    return {
        "baseline": baseline_val,
        "current": current_val,
        "delta": round(delta, 4),
        "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
        "direction": direction,
    }


def compare_metrics(
    baseline_metrics: Dict[str, float],
    current_metrics: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    """Compare all metrics between two runs."""
    all_keys = sorted(set(baseline_metrics.keys()) | set(current_metrics.keys()))
    result = {}

    for key in all_keys:
        if key in ("total_cases", "cases_with_golden_docs"):
            continue
        result[key] = _compute_delta(
            baseline_metrics.get(key),
            current_metrics.get(key),
            key,
        )

    return result


# =========================================================================
# Regression Detection
# =========================================================================
def detect_regressions(
    baseline_results: List[Dict[str, Any]],
    current_results: List[Dict[str, Any]],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """
    Detect per-example regressions between two runs.

    Compares matching test case IDs and finds cases where quality dropped.
    Returns top N worst regressions sorted by severity.
    """
    baseline_by_id = {r["id"]: r for r in baseline_results}
    current_by_id = {r["id"]: r for r in current_results}

    common_ids = set(baseline_by_id.keys()) & set(current_by_id.keys())

    regressions = []
    for case_id in common_ids:
        b = baseline_by_id[case_id]
        c = current_by_id[case_id]

        regression_score = 0.0
        reasons = []

        # Doc recall regression
        b_recall = b.get("doc_recall")
        c_recall = c.get("doc_recall")
        if b_recall is not None and c_recall is not None:
            if c_recall < b_recall:
                regression_score += (b_recall - c_recall)
                reasons.append(f"recall: {b_recall:.2f} -> {c_recall:.2f}")

        # Token F1 regression
        b_f1 = b.get("token_f1")
        c_f1 = c.get("token_f1")
        if b_f1 is not None and c_f1 is not None:
            if c_f1 < b_f1:
                regression_score += (b_f1 - c_f1)
                reasons.append(f"token_f1: {b_f1:.2f} -> {c_f1:.2f}")

        # Latency regression (>50% slower)
        b_lat = b.get("http_latency_ms")
        c_lat = c.get("http_latency_ms")
        if b_lat and c_lat and c_lat > b_lat * 1.5:
            regression_score += 0.3
            reasons.append(f"latency: {b_lat:.0f}ms -> {c_lat:.0f}ms (+{(c_lat/b_lat - 1)*100:.0f}%)")

        # New error
        if c.get("error") and not b.get("error"):
            regression_score += 2.0
            reasons.append(f"new_error: {c['error'][:80]}")

        if regression_score > 0:
            regressions.append({
                "example_id": case_id,
                "regression_score": round(regression_score, 3),
                "reasons": reasons,
                "baseline_recall": b_recall,
                "current_recall": c_recall,
                "baseline_f1": b_f1,
                "current_f1": c_f1,
                "baseline_latency": b_lat,
                "current_latency": c_lat,
            })

    regressions.sort(key=lambda x: x["regression_score"], reverse=True)
    return regressions[:top_n]


def detect_improvements(
    baseline_results: List[Dict[str, Any]],
    current_results: List[Dict[str, Any]],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """Detect per-example improvements between two runs."""
    baseline_by_id = {r["id"]: r for r in baseline_results}
    current_by_id = {r["id"]: r for r in current_results}

    common_ids = set(baseline_by_id.keys()) & set(current_by_id.keys())

    improvements = []
    for case_id in common_ids:
        b = baseline_by_id[case_id]
        c = current_by_id[case_id]

        improvement_score = 0.0
        reasons = []

        # Recall improvement
        b_recall = b.get("doc_recall")
        c_recall = c.get("doc_recall")
        if b_recall is not None and c_recall is not None and c_recall > b_recall:
            improvement_score += (c_recall - b_recall)
            reasons.append(f"recall: {b_recall:.2f} -> {c_recall:.2f}")

        # Token F1 improvement
        b_f1 = b.get("token_f1")
        c_f1 = c.get("token_f1")
        if b_f1 is not None and c_f1 is not None and c_f1 > b_f1:
            improvement_score += (c_f1 - b_f1)
            reasons.append(f"token_f1: {b_f1:.2f} -> {c_f1:.2f}")

        # Error fixed
        if b.get("error") and not c.get("error"):
            improvement_score += 2.0
            reasons.append("error_fixed")

        if improvement_score > 0:
            improvements.append({
                "example_id": case_id,
                "improvement_score": round(improvement_score, 3),
                "reasons": reasons,
            })

    improvements.sort(key=lambda x: x["improvement_score"], reverse=True)
    return improvements[:top_n]


# =========================================================================
# Config Diff
# =========================================================================
def diff_configs(
    baseline_params: Dict[str, str],
    current_params: Dict[str, str],
) -> List[Dict[str, str]]:
    """Find configuration differences between two runs."""
    # Skip non-config params
    skip = {"dataset_sha256", "run_config_sha256", "backend_config_sha256", "eval_code_git_sha"}
    all_keys = sorted(set(baseline_params.keys()) | set(current_params.keys()))

    diffs = []
    for key in all_keys:
        if key in skip:
            continue
        b_val = baseline_params.get(key)
        c_val = current_params.get(key)
        if b_val != c_val:
            diffs.append({"param": key, "baseline": b_val, "current": c_val})

    return diffs


# =========================================================================
# Main Compare Function
# =========================================================================
def compare_runs(
    baseline_run_id: str,
    current_run_id: str,
    tracking_uri: Optional[str] = None,
    top_n_regressions: int = 10,
) -> Dict[str, Any]:
    """
    Compare two evaluation runs end-to-end.

    Returns a structured report with:
    - metric deltas
    - config diffs
    - top regressions
    - top improvements
    """
    mlflow = _get_mlflow()
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    logger.info(f"Comparing runs: {baseline_run_id} (baseline) vs {current_run_id} (current)")

    # Load run data
    baseline = _load_run(mlflow, baseline_run_id)
    current = _load_run(mlflow, current_run_id)

    # Compare metrics
    metric_deltas = compare_metrics(baseline["metrics"], current["metrics"])

    # Config diffs
    config_diffs = diff_configs(baseline["params"], current["params"])

    # Per-example regressions
    baseline_results = _load_per_example_results(mlflow, baseline_run_id)
    current_results = _load_per_example_results(mlflow, current_run_id)

    regressions = []
    improvements = []
    if baseline_results and current_results:
        regressions = detect_regressions(
            baseline_results, current_results, top_n_regressions
        )
        improvements = detect_improvements(
            baseline_results, current_results, top_n_regressions
        )

    return {
        "baseline": {
            "run_id": baseline["run_id"],
            "run_name": baseline["run_name"],
            "start_time": baseline["start_time"].isoformat(),
            "dataset": baseline["params"].get("dataset_name", "unknown"),
        },
        "current": {
            "run_id": current["run_id"],
            "run_name": current["run_name"],
            "start_time": current["start_time"].isoformat(),
            "dataset": current["params"].get("dataset_name", "unknown"),
        },
        "metric_deltas": metric_deltas,
        "config_diffs": config_diffs,
        "regressions": regressions,
        "improvements": improvements,
        "summary": {
            "total_metrics_compared": len(metric_deltas),
            "metrics_improved": sum(1 for d in metric_deltas.values() if d["direction"] == "improved"),
            "metrics_regressed": sum(1 for d in metric_deltas.values() if d["direction"] == "regressed"),
            "metrics_unchanged": sum(1 for d in metric_deltas.values() if d["direction"] == "unchanged"),
            "per_example_regressions": len(regressions),
            "per_example_improvements": len(improvements),
            "config_changes": len(config_diffs),
        },
    }


# =========================================================================
# Report Formatting
# =========================================================================
def _format_delta(delta_info: Dict[str, Any]) -> str:
    """Format a single metric delta as a string."""
    baseline = delta_info["baseline"]
    current = delta_info["current"]
    delta = delta_info["delta"]
    delta_pct = delta_info["delta_pct"]
    direction = delta_info["direction"]

    if baseline is None:
        return f"  -- -> {current:.4f}" if current is not None else "  -- -> --"
    if current is None:
        return f"  {baseline:.4f} -> --"

    arrow = {"improved": "+", "regressed": "-", "unchanged": "=", "changed": "~"}.get(direction, "?")
    indicator = {"improved": "++", "regressed": "!!", "unchanged": "==", "changed": "~~"}.get(direction, "??")

    pct_str = f" ({delta_pct:+.1f}%)" if delta_pct is not None else ""
    return f"  {baseline:.4f} -> {current:.4f}  [{indicator} {delta:+.4f}{pct_str}]"


def format_report(report: Dict[str, Any]) -> str:
    """
    Format comparison report as pasteable markdown.

    This is the "Eval Summary" artifact for team updates.
    """
    lines = []
    lines.append("# Eval Run Comparison")
    lines.append("")
    lines.append(f"**Baseline:** {report['baseline']['run_name']} (`{report['baseline']['run_id'][:8]}`) — {report['baseline']['start_time'][:10]}")
    lines.append(f"**Current:**  {report['current']['run_name']} (`{report['current']['run_id'][:8]}`) — {report['current']['start_time'][:10]}")
    lines.append(f"**Dataset:**  baseline={report['baseline']['dataset']}, current={report['current']['dataset']}")
    lines.append("")

    # Summary
    s = report["summary"]
    lines.append("## Summary")
    lines.append(f"- Metrics improved: **{s['metrics_improved']}**")
    lines.append(f"- Metrics regressed: **{s['metrics_regressed']}**")
    lines.append(f"- Metrics unchanged: {s['metrics_unchanged']}")
    lines.append(f"- Config changes: {s['config_changes']}")
    lines.append(f"- Per-example regressions: {s['per_example_regressions']}")
    lines.append(f"- Per-example improvements: {s['per_example_improvements']}")
    lines.append("")

    # Metric deltas table
    lines.append("## Metric Deltas")
    lines.append("")
    lines.append("| Metric | Baseline | Current | Delta | Status |")
    lines.append("|--------|----------|---------|-------|--------|")

    # Group metrics
    quality_metrics = ["mean_doc_recall", "mean_doc_f1", "mean_mrr", "mean_ndcg_at_k",
                       "mean_token_f1", "mean_rouge_l", "mean_answer_relevance",
                       "mean_faithfulness", "citation_rate"]
    latency_metrics = ["mean_http_latency_ms", "p50_http_latency_ms", "p90_http_latency_ms",
                       "mean_e2e_ms", "mean_embedding_ms", "mean_retrieval_ms", "mean_llm_ms",
                       "p50_embedding_ms", "p90_embedding_ms",
                       "p50_retrieval_ms", "p90_retrieval_ms",
                       "p50_llm_ms", "p90_llm_ms"]

    def _add_metric_row(key: str, deltas: Dict) -> None:
        if key not in deltas:
            return
        d = deltas[key]
        b_str = f"{d['baseline']:.4f}" if d["baseline"] is not None else "--"
        c_str = f"{d['current']:.4f}" if d["current"] is not None else "--"
        delta_str = f"{d['delta']:+.4f}" if d["delta"] is not None else "--"
        status = {"improved": "++", "regressed": "!!", "unchanged": "==", "changed": "~~"}.get(d["direction"], "??")
        lines.append(f"| {key} | {b_str} | {c_str} | {delta_str} | {status} |")

    lines.append("| **Quality** | | | | |")
    for m in quality_metrics:
        _add_metric_row(m, report["metric_deltas"])

    lines.append("| **Latency** | | | | |")
    for m in latency_metrics:
        _add_metric_row(m, report["metric_deltas"])

    lines.append("")

    # Config diffs
    if report["config_diffs"]:
        lines.append("## Config Changes")
        lines.append("")
        lines.append("| Parameter | Baseline | Current |")
        lines.append("|-----------|----------|---------|")
        for diff in report["config_diffs"]:
            lines.append(f"| {diff['param']} | {diff['baseline'] or '--'} | {diff['current'] or '--'} |")
        lines.append("")

    # Regressions
    if report["regressions"]:
        lines.append("## Top Regressions")
        lines.append("")
        lines.append("| # | Example ID | Score | Reasons |")
        lines.append("|---|-----------|-------|---------|")
        for i, reg in enumerate(report["regressions"], 1):
            reasons_str = "; ".join(reg["reasons"])
            lines.append(f"| {i} | {reg['example_id']} | {reg['regression_score']:.3f} | {reasons_str} |")
        lines.append("")

    # Improvements
    if report["improvements"]:
        lines.append("## Top Improvements")
        lines.append("")
        lines.append("| # | Example ID | Score | Reasons |")
        lines.append("|---|-----------|-------|---------|")
        for i, imp in enumerate(report["improvements"], 1):
            reasons_str = "; ".join(imp["reasons"])
            lines.append(f"| {i} | {imp['example_id']} | {imp['improvement_score']:.3f} | {reasons_str} |")
        lines.append("")

    lines.append("---")
    lines.append(f"*Generated: {datetime.utcnow().isoformat()[:19]}Z*")
    return "\n".join(lines)


def save_report(report: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """Save comparison report as markdown and JSON."""
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"eval/reports/compare_{timestamp}"

    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save markdown
    md_path = output_dir / "comparison.md"
    md_path.write_text(format_report(report), encoding="utf-8")
    logger.info(f"Saved markdown report: {md_path}")

    # Save JSON
    json_path = output_dir / "comparison.json"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    logger.info(f"Saved JSON report: {json_path}")

    return str(output_dir)
