"""
MLflow Run Acceptance Test.

Verifies that the most recent MLflow run contains all required params and artifacts.

Usage:
    python eval/tools/verify_mlflow_run.py
    python eval/tools/verify_mlflow_run.py --experiment omnirag_offline_eval --run-id <id>

Exit codes:
    0: All checks pass
    1: Missing required params or artifacts
"""

import argparse
import sys
from typing import List, Set

try:
    import mlflow
    from mlflow.tracking import MlflowClient
except ImportError:
    print("ERROR: mlflow not installed. Run: pip install mlflow")
    sys.exit(1)


# Required MLflow params
REQUIRED_PARAMS = {
    # Dataset
    "dataset_sha256",
    "dataset_num_examples",
    # Backend config
    "backend_config_sha256",
    "run_config_sha256",
    # Retrieval
    "embedding_model",
    "embedding_dim",
    "dense_k",
    "rerank_enabled",
    "mmr_enabled",
    # Generation
    "llm_model",
    "llm_provider",
    "temperature",
    "max_tokens",
    "top_p",
    "timeout_seconds",
    # Infra
    "qdrant_collection",
}

# Required artifact path prefixes (at least one file matching each)
REQUIRED_ARTIFACT_PATTERNS = [
    "dataset/",            # Dataset file + manifest
    "config/backend_config_",
    "config/run_config_",
    "env/python_version_",
    "env/pip_freeze_",
    "examples/examples_",
    "results/eval_results_",
    "metrics/",            # slice_metrics or metrics_summary
]


def get_latest_run(client: MlflowClient, experiment_name: str) -> dict:
    """Get the most recent run in the experiment."""
    experiment = client.get_experiment_by_name(experiment_name)
    if not experiment:
        raise ValueError(f"Experiment '{experiment_name}' not found")
    
    runs = client.search_runs(
        experiment_ids=[experiment.experiment_id],
        order_by=["start_time DESC"],
        max_results=1,
    )
    
    if not runs:
        raise ValueError(f"No runs found in experiment '{experiment_name}'")
    
    return runs[0]


def verify_params(run, required: Set[str]) -> List[str]:
    """Check for missing required params."""
    params = run.data.params
    missing = [p for p in required if p not in params]
    return missing


def verify_artifacts(client: MlflowClient, run_id: str, patterns: List[str]) -> List[str]:
    """Check for missing required artifact patterns."""
    artifacts = []
    
    def list_all(path: str = ""):
        for item in client.list_artifacts(run_id, path):
            if item.is_dir:
                list_all(item.path)
            else:
                artifacts.append(item.path)
    
    list_all()
    
    missing = []
    for pattern in patterns:
        if not any(a.startswith(pattern) or pattern.rstrip("/") in a for a in artifacts):
            missing.append(pattern)
    
    return missing


def main():
    parser = argparse.ArgumentParser(description="Verify MLflow run completeness")
    parser.add_argument("--experiment", default="omnirag_offline_eval", help="Experiment name")
    parser.add_argument("--run-id", help="Specific run ID (default: latest)")
    parser.add_argument("--tracking-uri", default="file:./mlruns", help="MLflow tracking URI")
    args = parser.parse_args()
    
    mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient()
    
    print(f"MLflow tracking URI: {args.tracking_uri}")
    print(f"Experiment: {args.experiment}")
    
    # Get run
    if args.run_id:
        run = client.get_run(args.run_id)
        print(f"Run ID: {args.run_id}")
    else:
        run = get_latest_run(client, args.experiment)
        print(f"Latest run ID: {run.info.run_id}")
    
    print(f"Run name: {run.info.run_name}")
    print()
    
    # Check params
    print("=" * 60)
    print("PARAM VERIFICATION")
    print("=" * 60)
    missing_params = verify_params(run, REQUIRED_PARAMS)
    
    if missing_params:
        print(f"❌ MISSING PARAMS ({len(missing_params)}):")
        for p in sorted(missing_params):
            print(f"   - {p}")
    else:
        print(f"✓ All {len(REQUIRED_PARAMS)} required params present")
    
    # Show actual params
    print("\nActual params logged:")
    for k, v in sorted(run.data.params.items()):
        print(f"   {k}: {v[:50]}..." if len(str(v)) > 50 else f"   {k}: {v}")
    
    print()
    print("=" * 60)
    print("ARTIFACT VERIFICATION")
    print("=" * 60)
    missing_artifacts = verify_artifacts(client, run.info.run_id, REQUIRED_ARTIFACT_PATTERNS)
    
    if missing_artifacts:
        print(f"❌ MISSING ARTIFACT PATTERNS ({len(missing_artifacts)}):")
        for p in sorted(missing_artifacts):
            print(f"   - {p}")
    else:
        print(f"✓ All {len(REQUIRED_ARTIFACT_PATTERNS)} required artifact patterns present")
    
    # Show actual artifacts
    print("\nArtifacts found:")
    for item in client.list_artifacts(run.info.run_id):
        if item.is_dir:
            print(f"   📁 {item.path}/")
            for sub in client.list_artifacts(run.info.run_id, item.path):
                print(f"      - {sub.path}")
        else:
            print(f"   📄 {item.path}")
    
    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if missing_params or missing_artifacts:
        print("❌ VERIFICATION FAILED")
        if missing_params:
            print(f"   Missing params: {', '.join(missing_params)}")
        if missing_artifacts:
            print(f"   Missing artifacts: {', '.join(missing_artifacts)}")
        return 1
    
    print("✓ ALL CHECKS PASSED")
    print("  Run is reviewer-proof!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
