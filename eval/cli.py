"""
CLI entrypoint for OmniRAG Offline Evaluation.

Version: 2.1.0 - With run comparison and report generation.

Usage:
    # Basic evaluation
    python -m eval.cli run --dataset eval/datasets/demo_v2.jsonl

    # Compare two runs
    python -m eval.cli compare --baseline <run_id> --current <run_id>
    python -m eval.cli compare --last 2

    # Generate summary report from a run
    python -m eval.cli report --run-id <run_id>
    python -m eval.cli report --latest

    # Dry run (validate dataset only)
    python -m eval.cli run --dataset eval/datasets/demo_v2.jsonl --dry-run

    # Legacy (no subcommand = run)
    python -m eval.cli --dataset eval/datasets/sample.jsonl

    # View results
    mlflow ui --backend-store-uri file:./mlruns --port 5000

Environment Variables:
    EVAL_BACKEND_URL: Backend API URL
    EVAL_ACCESS_TOKEN: JWT access token for API calls
    MLFLOW_TRACKING_URI: MLflow tracking server URI
    EVAL_EXPERIMENT_NAME: MLflow experiment name
    EVAL_LLM_MODEL: Model for LLM-based evaluation (optional)
    EVAL_LLM_PROVIDER: LLM provider for evaluation
    EVAL_ENABLE_LLM_EVAL: Enable/disable LLM-based evaluation (default: false)
    EVAL_LOG_FULL_CONTEXT: Log full context in artifacts (default: false)
    EVAL_REDACT_ARTIFACTS: Redact PII from artifacts (default: true)
    EVAL_ENABLE_ROUGE: Enable ROUGE-L metric (default: false)
"""

import argparse
import logging
import sys
from typing import Optional

from eval.config import EvalSettings
from eval.runner import run_eval, run_eval_dry

_SUBCOMMANDS = {"run", "compare", "report"}


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the CLI."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# =========================================================================
# Parser builders
# =========================================================================
def _build_run_parser() -> argparse.ArgumentParser:
    """Build parser for the 'run' command (also used for legacy mode)."""
    parser = argparse.ArgumentParser(
        prog="python -m eval.cli run",
        description="Run OmniRAG RAG offline evaluation",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--dataset", "-d", type=str, required=True, help="JSONL dataset path")
    parser.add_argument("--experiment", "-e", type=str, default=None, help="MLflow experiment name")
    parser.add_argument("--backend-url", "-b", type=str, default=None, help="Backend API URL")
    parser.add_argument("--access-token", "-t", type=str, default=None, help="JWT access token")
    parser.add_argument("--mlflow-uri", type=str, default=None, help="MLflow tracking URI")
    parser.add_argument("--no-llm-eval", action="store_true", help="Disable LLM-based eval metrics")
    parser.add_argument("--llm-eval-model", type=str, default=None, help="LLM eval model")
    parser.add_argument("--llm-eval-provider", type=str, default=None, choices=["openrouter", "vertex-ai", "gemini"])
    parser.add_argument("--timeout", type=float, default=None, help="HTTP timeout (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset only")
    parser.add_argument("--log-full-context", action="store_true", help="Log full context in artifacts")
    parser.add_argument("--max-chunks-logged", type=int, default=None, help="Max chunks per example")
    parser.add_argument("--no-redact-artifacts", action="store_true", help="Disable PII redaction")
    parser.add_argument("--compress-artifacts", action="store_true", help="Gzip compress artifacts")
    parser.add_argument("--enable-rouge", action="store_true", help="Enable ROUGE-L metric")
    return parser


def _build_compare_parser() -> argparse.ArgumentParser:
    """Build parser for the 'compare' command."""
    parser = argparse.ArgumentParser(
        prog="python -m eval.cli compare",
        description="Compare two evaluation runs",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--baseline", type=str, default=None, help="Baseline MLflow run ID")
    parser.add_argument("--current", type=str, default=None, help="Current MLflow run ID")
    parser.add_argument("--last", type=int, default=None, help="Compare N most recent runs (newest=current)")
    parser.add_argument("--experiment", "-e", type=str, default=None, help="MLflow experiment name")
    parser.add_argument("--mlflow-uri", type=str, default=None, help="MLflow tracking URI")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output directory for report")
    parser.add_argument("--top-n", type=int, default=10, help="Top N regressions/improvements")
    return parser


def _build_report_parser() -> argparse.ArgumentParser:
    """Build parser for the 'report' command."""
    parser = argparse.ArgumentParser(
        prog="python -m eval.cli report",
        description="Generate summary report for a run",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--run-id", type=str, default=None, help="MLflow run ID")
    parser.add_argument("--latest", action="store_true", help="Use most recent run")
    parser.add_argument("--experiment", "-e", type=str, default=None, help="MLflow experiment name")
    parser.add_argument("--mlflow-uri", type=str, default=None, help="MLflow tracking URI")
    return parser


# =========================================================================
# Settings builder
# =========================================================================
def build_settings(args: argparse.Namespace) -> EvalSettings:
    """Build EvalSettings from CLI arguments and environment variables."""
    overrides = {}

    if args.backend_url:
        overrides["backend_url"] = args.backend_url
    if args.access_token:
        overrides["access_token"] = args.access_token
    if args.mlflow_uri:
        overrides["mlflow_tracking_uri"] = args.mlflow_uri
    if args.experiment:
        overrides["experiment_name"] = args.experiment
    if args.no_llm_eval:
        overrides["enable_llm_eval"] = False
    if args.llm_eval_model:
        overrides["llm_eval_model"] = args.llm_eval_model
    if args.llm_eval_provider:
        overrides["llm_eval_provider"] = args.llm_eval_provider
    if args.timeout:
        overrides["request_timeout"] = args.timeout
    if args.log_full_context:
        overrides["log_full_context"] = True
    if args.max_chunks_logged:
        overrides["max_chunks_logged"] = args.max_chunks_logged
    if args.no_redact_artifacts:
        overrides["redact_artifacts"] = False
    if args.compress_artifacts:
        overrides["compress_artifacts"] = True
    if args.enable_rouge:
        overrides["enable_rouge"] = True

    return EvalSettings(**overrides)


def get_cli_args_dict(args: argparse.Namespace) -> dict:
    """Convert CLI args to dict for logging."""
    return {
        "dataset": args.dataset,
        "experiment": args.experiment,
        "backend_url": args.backend_url,
        "access_token_provided": bool(args.access_token),
        "no_llm_eval": args.no_llm_eval,
        "llm_eval_model": args.llm_eval_model,
        "llm_eval_provider": args.llm_eval_provider,
        "log_full_context": args.log_full_context,
        "max_chunks_logged": args.max_chunks_logged,
        "no_redact_artifacts": args.no_redact_artifacts,
        "compress_artifacts": args.compress_artifacts,
        "enable_rouge": args.enable_rouge,
    }


# =========================================================================
# Command handlers
# =========================================================================
def _handle_run(args, logger) -> int:
    """Handle the 'run' command."""
    try:
        settings = build_settings(args)
    except Exception as e:
        logger.error(f"Failed to load settings: {e}")
        return 1

    if not args.dry_run and not settings.access_token:
        logger.error(
            "Access token is required. Set EVAL_ACCESS_TOKEN environment variable "
            "or use --access-token flag."
        )
        return 1

    try:
        if args.dry_run:
            logger.info("Running in dry-run mode (dataset validation only)")
            test_cases = run_eval_dry(args.dataset, settings)
            logger.info(f"Dataset valid: {len(test_cases)} test cases")
            return 0

        logger.info("Starting evaluation pipeline")
        cli_args = get_cli_args_dict(args)
        results = run_eval(args.dataset, settings, cli_args=cli_args)

        print("\n" + "=" * 60)
        print("EVALUATION COMPLETE")
        print("=" * 60)
        print(f"MLflow Run ID: {results['run_id']}")
        print(f"Test Cases: {results['num_cases']}")
        print(f"Errors: {results['num_errors']}")
        print("\nAggregated Metrics:")
        for key, value in sorted(results['aggregated_metrics'].items()):
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")
        print("\nView results:")
        print(f"  mlflow ui --backend-store-uri {settings.mlflow_tracking_uri} --port 5000")
        print("=" * 60)
        return 0

    except FileNotFoundError as e:
        logger.error(f"Dataset file not found: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Evaluation failed: {e}")
        return 1


def _handle_compare(args, logger) -> int:
    """Handle the 'compare' command."""
    from eval.compare import compare_runs, format_report, get_latest_runs, save_report

    import os
    tracking_uri = args.mlflow_uri or os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
    experiment = args.experiment or os.getenv("EVAL_EXPERIMENT_NAME", "omnirag_offline_eval")

    try:
        if args.last:
            logger.info(f"Fetching {args.last} most recent runs from '{experiment}'")
            run_ids = get_latest_runs(experiment, args.last, tracking_uri)
            baseline_id = run_ids[-1]  # oldest
            current_id = run_ids[0]    # newest
        elif args.baseline and args.current:
            baseline_id = args.baseline
            current_id = args.current
        else:
            logger.error("Provide either --baseline + --current or --last N")
            return 1

        report = compare_runs(
            baseline_run_id=baseline_id,
            current_run_id=current_id,
            tracking_uri=tracking_uri,
            top_n_regressions=args.top_n,
        )

        print(format_report(report))

        if args.output:
            save_report(report, args.output)
            logger.info(f"Report saved to: {args.output}")

        return 0

    except Exception as e:
        logger.exception(f"Comparison failed: {e}")
        return 1


def _handle_report(args, logger) -> int:
    """Handle the 'report' command — single-run summary."""
    from eval.compare import _get_mlflow, _load_run, _load_failures

    import os
    tracking_uri = args.mlflow_uri or os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
    experiment = args.experiment or os.getenv("EVAL_EXPERIMENT_NAME", "omnirag_offline_eval")

    try:
        mlflow = _get_mlflow()
        mlflow.set_tracking_uri(tracking_uri)

        if args.latest:
            from eval.compare import get_latest_runs
            run_ids = get_latest_runs(experiment, 1, tracking_uri)
            run_id = run_ids[0]
        elif args.run_id:
            run_id = args.run_id
        else:
            logger.error("Provide either --run-id or --latest")
            return 1

        run_data = _load_run(mlflow, run_id)
        failures = _load_failures(mlflow, run_id)

        lines = []
        lines.append("# Eval Run Summary")
        lines.append("")
        lines.append(f"**Run:** {run_data['run_name']} (`{run_id[:8]}`)")
        lines.append(f"**Date:** {run_data['start_time'].strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Status:** {run_data['status']}")
        lines.append(f"**Dataset:** {run_data['params'].get('dataset_name', 'unknown')}")
        lines.append("")

        lines.append("## Configuration")
        config_keys = ["embedding_model", "llm_model", "llm_provider", "rerank_enabled",
                       "dense_k", "temperature", "dataset_num_examples"]
        for key in config_keys:
            val = run_data["params"].get(key)
            if val is not None:
                lines.append(f"- **{key}:** {val}")
        lines.append("")

        lines.append("## Metrics")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")

        quality = ["mean_doc_recall", "mean_doc_f1", "mean_mrr", "mean_ndcg_at_k",
                    "mean_token_f1", "mean_answer_relevance", "citation_rate"]
        latency = ["mean_http_latency_ms", "p50_http_latency_ms", "p90_http_latency_ms",
                    "mean_embedding_ms", "p50_embedding_ms", "p90_embedding_ms",
                    "mean_retrieval_ms", "p50_retrieval_ms", "p90_retrieval_ms",
                    "mean_llm_ms", "p50_llm_ms", "p90_llm_ms"]

        lines.append("| **Quality** | |")
        for key in quality:
            val = run_data["metrics"].get(key)
            if val is not None:
                lines.append(f"| {key} | {val:.4f} |")

        lines.append("| **Latency (ms)** | |")
        for key in latency:
            val = run_data["metrics"].get(key)
            if val is not None:
                lines.append(f"| {key} | {val:.1f} |")

        total = run_data["metrics"].get("total_cases", 0)
        errors = run_data["metrics"].get("cases_with_errors", 0)
        lines.append(f"| total_cases | {total:.0f} |")
        lines.append(f"| cases_with_errors | {errors:.0f} |")
        lines.append("")

        if failures:
            lines.append("## Top Failures")
            lines.append("")
            lines.append("| # | Example ID | Score | Reasons |")
            lines.append("|---|-----------|-------|---------|")
            for i, f in enumerate(failures[:10], 1):
                reasons = ", ".join(f.get("reason_codes", []))
                lines.append(f"| {i} | {f['example_id']} | {f['failure_score']:.3f} | {reasons} |")
            lines.append("")

        from datetime import datetime
        lines.append("---")
        lines.append(f"*Generated: {datetime.utcnow().isoformat()[:19]}Z*")

        print("\n".join(lines))
        return 0

    except Exception as e:
        logger.exception(f"Report generation failed: {e}")
        return 1


# =========================================================================
# Main entrypoint
# =========================================================================
def main(argv: Optional[list] = None) -> int:
    """
    Main CLI entrypoint. Detects subcommand and routes to appropriate handler.

    Supports both new subcommand style and legacy flat style:
        python -m eval.cli run --dataset ...       # new
        python -m eval.cli --dataset ...           # legacy (= run)
        python -m eval.cli compare --last 2        # new
        python -m eval.cli report --latest         # new
    """
    raw_args = argv if argv is not None else sys.argv[1:]

    # Detect subcommand
    command = raw_args[0] if raw_args and raw_args[0] in _SUBCOMMANDS else None
    remaining = raw_args[1:] if command else raw_args

    if command == "compare":
        parser = _build_compare_parser()
        args = parser.parse_args(remaining)
        setup_logging(verbose=args.verbose)
        return _handle_compare(args, logging.getLogger(__name__))

    if command == "report":
        parser = _build_report_parser()
        args = parser.parse_args(remaining)
        setup_logging(verbose=args.verbose)
        return _handle_report(args, logging.getLogger(__name__))

    if command == "run" or remaining:
        parser = _build_run_parser()
        args = parser.parse_args(remaining)
        setup_logging(verbose=args.verbose)
        return _handle_run(args, logging.getLogger(__name__))

    # No args at all
    print("OmniRAG RAG Offline Evaluation Pipeline v2.1.0")
    print()
    print("Commands:")
    print("  run      Run evaluation pipeline")
    print("  compare  Compare two evaluation runs")
    print("  report   Generate summary report for a run")
    print()
    print("Examples:")
    print("  python -m eval.cli run --dataset eval/datasets/demo_v2.jsonl")
    print("  python -m eval.cli compare --last 2")
    print("  python -m eval.cli report --latest")
    print("  python -m eval.cli --dataset eval/datasets/sample.jsonl  # legacy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
