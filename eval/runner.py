"""
Evaluation Runner for OmniRAG RAG System.

Version: 2.0.0 - Industry-standard reproducible evaluation harness.

This module orchestrates the evaluation pipeline:
1. Load test cases from dataset
2. Execute queries against the RAG system
3. Compute metrics for each test case
4. Aggregate and log results to MLflow with full reproducibility artifacts

Example:
    from eval.runner import run_eval
    from eval.config import EvalSettings

    settings = EvalSettings(
        backend_url="http://localhost:8081",
        access_token="your-jwt",
    )

    run_eval("eval/datasets/sample.jsonl", settings)
"""

import csv
import gzip
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eval.client import OmniRAGClient, OmniRAGClientError
from eval.config import (
    DATASET_SCHEMA_VERSION,
    EVAL_HARNESS_VERSION,
    EVAL_SCHEMA_VERSION,
    EvalSettings,
    canonical_json,
    compute_sha256,
)
from eval.dataset import EvalTestCase, load_dataset
from eval.metrics import (
    PerCaseMetrics,
    aggregate_metrics,
    compute_failure_score,
    compute_per_case_metrics,
    extract_compact_citations,
    metrics_to_dict,
)

try:
    from eval.utils.language import detect_language
except ImportError:
    def detect_language(text: str) -> str:
        return "unknown"

try:
    from eval.utils.redaction import redact_text
except ImportError:
    def redact_text(text: str) -> str:
        return text

logger = logging.getLogger(__name__)

# MLflow import
try:
    import mlflow
except ImportError:
    mlflow = None


# =============================================================================
# Git & Environment Provenance
# =============================================================================
def get_git_commit_hash() -> Optional[str]:
    """Get the current git commit hash (short)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Could not get git commit hash: {e}")
    return None


def log_environment_artifacts() -> None:
    """Log Python version and pip freeze as artifacts."""
    if mlflow is None:
        return
    
    # Python version
    python_info = f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\n{sys.version}"
    with tempfile.NamedTemporaryFile("w", suffix=".txt", prefix="python_version_", delete=False) as f:
        f.write(python_info)
        temp_path = f.name
    mlflow.log_artifact(temp_path, "env")
    os.unlink(temp_path)
    
    # Pip freeze (best-effort)
    try:
        result = subprocess.run(["pip", "freeze"], capture_output=True, text=True, timeout=30)
        with tempfile.NamedTemporaryFile("w", suffix=".txt", prefix="pip_freeze_", delete=False) as f:
            f.write(result.stdout)
            temp_path = f.name
        mlflow.log_artifact(temp_path, "env")
        os.unlink(temp_path)
    except Exception as e:
        logger.warning(f"pip freeze unavailable: {e}")


# =============================================================================
# Dataset Manifest
# =============================================================================
def create_dataset_manifest(dataset_path: str, test_cases: List[EvalTestCase]) -> Dict[str, Any]:
    """Create dataset manifest with full metadata."""
    file_path = Path(dataset_path)
    
    # Compute SHA256 from bytes
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(block)
    
    return {
        "eval_schema_version": EVAL_SCHEMA_VERSION,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "dataset_sha256": sha256_hash.hexdigest(),
        "dataset_name": file_path.stem,
        "original_filename": file_path.name,
        "dataset_num_examples": len(test_cases),
        "with_golden_docs": sum(1 for c in test_cases if c.golden_docs),
        "with_golden_answer": sum(1 for c in test_cases if c.golden_answer),
    }


# =============================================================================
# Backend Config Fetching
# =============================================================================
def fetch_backend_config(client: OmniRAGClient) -> Optional[Dict[str, Any]]:
    """Fetch runtime config from backend's /api/system/config endpoint."""
    import httpx
    
    try:
        url = f"{client.base_url.rstrip('/')}/api/system/config"
        headers = client._get_headers() if client.access_token else None
        response = httpx.get(url, headers=headers, timeout=10.0)
        if response.status_code == 200:
            return response.json()
        else:
            logger.warning(f"Backend config fetch failed: HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"Could not fetch backend config: {e}")
    return None


# =============================================================================
# Run Config & Manifest
# =============================================================================
def create_run_config(
    settings: EvalSettings,
    dataset_manifest: Dict[str, Any],
    backend_config: Optional[Dict[str, Any]],
    cli_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create consolidated run config for reproducibility."""
    return {
        "eval_schema_version": EVAL_SCHEMA_VERSION,
        "eval_harness_version": EVAL_HARNESS_VERSION,
        "dataset": dataset_manifest,
        "backend_config": backend_config,
        "eval_settings": {
            "access_token_set": bool(settings.access_token),
            "enable_llm_eval": settings.enable_llm_eval,
            "enable_rouge": settings.enable_rouge,
            "log_full_context": settings.log_full_context,
            "max_chunks_logged": settings.max_chunks_logged,
            "max_context_chars_per_chunk": settings.max_context_chars_per_chunk,
            "redact_artifacts": settings.redact_artifacts,
        },
        "cli_args": cli_args or {},
    }


def create_run_manifest(
    dataset_manifest: Dict[str, Any],
    backend_config: Optional[Dict[str, Any]],
    run_config: Dict[str, Any],
    commit_hash: Optional[str],
    settings: EvalSettings,
) -> Dict[str, Any]:
    """Create run manifest for full reproducibility."""
    backend_sha = compute_sha256(backend_config) if backend_config else None
    run_config_sha = compute_sha256(run_config)
    
    manifest = {
        "eval_schema_version": EVAL_SCHEMA_VERSION,
        "eval_harness_version": EVAL_HARNESS_VERSION,
        "start_timestamp": datetime.utcnow().isoformat() + "Z",
        "eval_code_git_sha": commit_hash,
        "backend_config_sha256": backend_sha,
        "run_config_sha256": run_config_sha,
        "dataset": dataset_manifest,
    }
    
    if settings.enable_llm_eval:
        manifest["judge_config"] = {
            "provider": settings.llm_eval_provider,
            "model": settings.llm_eval_model,
            "temperature": 0,
        }
    
    return manifest


# =============================================================================
# Forensic Example Artifact Builder
# =============================================================================
def build_example_artifact(
    test_case: EvalTestCase,
    response: Any,
    metrics: PerCaseMetrics,
    trace_data: Optional[Dict[str, Any]],
    settings: EvalSettings,
) -> Dict[str, Any]:
    """Build per-example forensic artifact with privacy controls."""
    # Compact citations
    citations = extract_compact_citations(response.citations if hasattr(response, 'citations') else [])
    
    # Retrieval records
    retrieval = []
    for s in response.sources[:settings.max_chunks_logged]:
        retrieval.append({
            "chunk_id": s.chunk_id,
            "doc_id": s.doc_id,
            "doc_name": s.doc_name,
            "page": s.page,
            "score": s.score,
            "rerank_score": s.metadata.get("rerank_score") if s.metadata else None,
            "section": s.metadata.get("section") if s.metadata else None,
            "metadata": {
                "language": s.metadata.get("language") if s.metadata else None,
                "doc_type": s.metadata.get("doc_type") if s.metadata else None,
                "is_ocr": s.metadata.get("is_ocr") if s.metadata else None,
            }
        })
    
    # Build artifact
    artifact = {
        "eval_schema_version": EVAL_SCHEMA_VERSION,
        "example_id": test_case.id,
        "query": test_case.query,
        "expected_answer": test_case.golden_answer,
        "predicted_answer": response.answer,
        "citations": citations,
        "retrieval": retrieval,
        "trace": {
            "trace_id": response.trace_id if hasattr(response, 'trace_id') else None,
            "trace_steps": trace_data.get("steps") if trace_data else None,
        },
        "eval_diagnostics": {
            "http_latency_ms": response.http_latency_ms if hasattr(response, 'http_latency_ms') else None,
            "tokens_in": trace_data.get("tokens_in") if trace_data else None,
            "tokens_out": trace_data.get("tokens_out") if trace_data else None,
        },
        "detected_language": detect_language(test_case.query),
    }
    
    # Context with privacy controls
    sources = response.sources[:settings.max_chunks_logged]
    if settings.log_full_context:
        texts = [s.text[:settings.max_context_chars_per_chunk] for s in sources if s.text]
        if settings.redact_artifacts:
            texts = [redact_text(t) for t in texts]
        artifact["context"] = {"selected_context_text": "\n---\n".join(texts)}
    else:
        previews = [s.text[:200] if s.text else "" for s in sources]
        if settings.redact_artifacts:
            previews = [redact_text(p) for p in previews]
        artifact["context"] = {
            "selected_context_hashes": [
                hashlib.sha256(s.text.encode()).hexdigest()[:16] if s.text else ""
                for s in sources
            ],
            "chunk_ids": [s.chunk_id for s in sources],
            "previews": previews,
        }
    
    return artifact


# =============================================================================
# Slice Metrics
# =============================================================================
def compute_slice_metrics(
    all_metrics: List[PerCaseMetrics],
    all_examples: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute metrics breakdown with provided vs inferred tracking."""
    from collections import defaultdict
    
    slices = {
        "by_language": defaultdict(list),
        "by_doc_type": defaultdict(list),
        "by_is_ocr": defaultdict(list),
    }
    slice_sources = {
        "by_language": {},
        "by_doc_type": {},
        "by_is_ocr": {},
    }
    
    for m, ex in zip(all_metrics, all_examples):
        # Language
        lang = ex.get("detected_language", "unknown")
        slices["by_language"][lang].append(m)
        slice_sources["by_language"][lang] = "inferred"
        
        # Doc type (from retrieval metadata)
        doc_types = [r.get("metadata", {}).get("doc_type") for r in ex.get("retrieval", [])]
        doc_types = [dt for dt in doc_types if dt]
        doc_type = max(set(doc_types), key=doc_types.count) if doc_types else "unknown"
        slices["by_doc_type"][doc_type].append(m)
        slice_sources["by_doc_type"][doc_type] = "inferred"
        
        # OCR
        is_ocr = any(r.get("metadata", {}).get("is_ocr") for r in ex.get("retrieval", []))
        ocr_key = "ocr" if is_ocr else "non_ocr"
        slices["by_is_ocr"][ocr_key].append(m)
        slice_sources["by_is_ocr"][ocr_key] = "inferred"
    
    result = {"eval_schema_version": EVAL_SCHEMA_VERSION}
    
    for slice_type, data in slices.items():
        result[slice_type] = {}
        for val, metrics_list in data.items():
            if not metrics_list:
                continue
            agg = aggregate_metrics(metrics_list)
            
            # Worst examples by failure score
            scored = [(compute_failure_score(m)[0], m.id) for m in metrics_list]
            scored.sort(reverse=True)
            
            result[slice_type][val] = {
                "count": len(metrics_list),
                "source": slice_sources[slice_type].get(val, "inferred"),
                "mean_doc_recall": agg.get("mean_doc_recall"),
                "mean_token_f1": agg.get("mean_token_f1"),
                "p50_latency_ms": agg.get("p50_http_latency_ms"),
                "p90_latency_ms": agg.get("p90_http_latency_ms"),
                "worst_10_ids": [eid for _, eid in scored[:10]],
            }
    
    return result


# =============================================================================
# Top Failures with Reason Codes
# =============================================================================
def get_top_failures(
    all_metrics: List[PerCaseMetrics],
    all_examples: List[Dict[str, Any]],
    top_n: int = 20,
) -> List[Dict[str, Any]]:
    """Get top failures with explicit failure scores and reason codes."""
    failures = []
    
    for m, ex in zip(all_metrics, all_examples):
        score, reasons = compute_failure_score(m)
        failures.append({
            "example_id": m.id,
            "failure_score": round(score, 3),
            "reason_codes": reasons,
            "doc_recall": m.doc_recall,
            "mrr": m.mrr,
            "token_f1": m.token_f1,
            "latency_ms": m.http_latency_ms,
            "query_snippet": ex.get("query", "")[:100],
        })
    
    failures.sort(key=lambda x: x["failure_score"], reverse=True)
    return failures[:top_n]


# =============================================================================
# Metrics Summary
# =============================================================================
def create_metrics_summary(
    all_metrics: List[PerCaseMetrics],
    all_examples: List[Dict[str, Any]],
    top_n_failures: int = 20,
) -> Dict[str, Any]:
    """Create comprehensive metrics summary."""
    if not all_metrics:
        return {"eval_schema_version": EVAL_SCHEMA_VERSION, "total_cases": 0}
    
    agg = aggregate_metrics(all_metrics)
    
    # Get worst examples
    failures = get_top_failures(all_metrics, all_examples, top_n_failures)
    
    return {
        "eval_schema_version": EVAL_SCHEMA_VERSION,
        **agg,
        "worst_examples": [
            {"example_id": f["example_id"], "failure_score": f["failure_score"], "query_snippet": f["query_snippet"]}
            for f in failures
        ],
    }


# =============================================================================
# Single Case Evaluation
# =============================================================================
def evaluate_single_case(
    client: OmniRAGClient,
    test_case: EvalTestCase,
    settings: EvalSettings,
) -> Tuple[PerCaseMetrics, Dict[str, Any]]:
    """Evaluate a single test case and return metrics + forensic artifact."""
    logger.info(f"Evaluating: {test_case.id}")
    
    try:
        response = client.chat(query=test_case.query)
        
        # Fetch trace
        trace_data = None
        if response.trace_id:
            try:
                trace_data = client.get_trace(response.trace_id)
            except OmniRAGClientError as e:
                logger.warning(f"Trace fetch failed: {e}")
        
        # Compute metrics
        metrics = compute_per_case_metrics(
            test_case_id=test_case.id,
            golden_docs=test_case.golden_docs,
            golden_doc_ids=getattr(test_case, 'golden_doc_ids', None),
            retrieved_sources=response.sources,
            query=test_case.query,
            answer=response.answer,
            http_latency_ms=response.http_latency_ms,
            trace_data=trace_data,
            golden_answer=test_case.golden_answer,
            citations=response.citations if hasattr(response, 'citations') else [],
            enable_llm_eval=settings.enable_llm_eval,
            enable_rouge=settings.enable_rouge,
            llm_eval_model=settings.llm_eval_model,
            llm_eval_provider=settings.llm_eval_provider,
        )
        
        artifact = build_example_artifact(test_case, response, metrics, trace_data, settings)
        
        return metrics, artifact
        
    except OmniRAGClientError as e:
        logger.error(f"Test case {test_case.id} failed: {e}")
        metrics = PerCaseMetrics(id=test_case.id, error=str(e), golden_doc_names=test_case.golden_docs or [])
        artifact = {
            "eval_schema_version": EVAL_SCHEMA_VERSION,
            "example_id": test_case.id,
            "query": test_case.query,
            "expected_answer": test_case.golden_answer,
            "predicted_answer": "",
            "error": str(e),
            "detected_language": detect_language(test_case.query),
        }
        return metrics, artifact


# =============================================================================
# Artifact Saving
# =============================================================================
def save_jsonl_artifact(data: List[Dict], prefix: str, compress: bool = False) -> str:
    """Save list of dicts as JSONL, optionally gzipped."""
    suffix = ".jsonl.gz" if compress else ".jsonl"
    
    with tempfile.NamedTemporaryFile("wb" if compress else "w", suffix=suffix, prefix=prefix, delete=False) as f:
        if compress:
            with gzip.open(f, "wt", encoding="utf-8") as gz:
                for item in data:
                    gz.write(json.dumps(item, ensure_ascii=False) + "\n")
        else:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return f.name


def save_results_artifact(metrics_list: List[PerCaseMetrics], format: str = "jsonl") -> str:
    """Save per-case results as JSONL or CSV."""
    if format == "jsonl":
        data = [metrics_to_dict(m) for m in metrics_list]
        return save_jsonl_artifact(data, "eval_results_")
    else:
        suffix = ".csv"
        with tempfile.NamedTemporaryFile("w", suffix=suffix, prefix="eval_results_", delete=False, newline="", encoding="utf-8") as f:
            if metrics_list:
                sample = metrics_to_dict(metrics_list[0])
                writer = csv.DictWriter(f, fieldnames=list(sample.keys()))
                writer.writeheader()
                for m in metrics_list:
                    d = metrics_to_dict(m)
                    # Flatten lists for CSV
                    for k, v in d.items():
                        if isinstance(v, list):
                            d[k] = ", ".join(str(x) for x in v)
                    writer.writerow(d)
            return f.name


# =============================================================================
# Main Run Function
# =============================================================================
def run_eval(
    dataset_path: str,
    settings: EvalSettings,
    cli_args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run the evaluation pipeline with full MLflow logging.
    
    Returns dict with run_id, aggregated_metrics, num_cases, num_errors.
    """
    if mlflow is None:
        raise ImportError("MLflow required. Install with: pip install mlflow")
    
    logger.info("Starting evaluation run")
    logger.info(f"  Dataset: {dataset_path}")
    logger.info(f"  Backend: {settings.backend_url}")
    
    if not settings.access_token:
        raise ValueError(
            "Access token is required for evaluation. "
            "Set EVAL_ACCESS_TOKEN or pass access_token in EvalSettings."
        )
    
    # Load dataset
    test_cases = load_dataset(dataset_path)
    logger.info(f"Loaded {len(test_cases)} test cases")
    
    # Create client
    client = OmniRAGClient(
        base_url=settings.backend_url,
        access_token=settings.access_token,
        timeout=settings.request_timeout,
    )
    
    # Health check
    if not client.health_check():
        logger.warning("Backend health check failed")
    
    # Git commit
    commit_hash = get_git_commit_hash()
    
    # Fetch backend config
    backend_config = fetch_backend_config(client)
    
    # Create manifests
    dataset_manifest = create_dataset_manifest(dataset_path, test_cases)
    run_config = create_run_config(settings, dataset_manifest, backend_config, cli_args)
    run_manifest = create_run_manifest(dataset_manifest, backend_config, run_config, commit_hash, settings)
    
    # Configure MLflow
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.experiment_name)
    
    all_metrics: List[PerCaseMetrics] = []
    all_examples: List[Dict[str, Any]] = []
    
    run_name = f"eval_{dataset_manifest['dataset_name']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    with mlflow.start_run(run_name=run_name):
        # =================================================================
        # MLflow Tags (for UI filtering)
        # =================================================================
        mlflow.set_tag("run_type", "offline_eval")
        mlflow.set_tag("dataset_sha256", dataset_manifest["dataset_sha256"])
        mlflow.set_tag("dataset_name", dataset_manifest["dataset_name"])
        mlflow.set_tag("backend_url", settings.backend_url)
        mlflow.set_tag("auth_mode", "jwt")
        mlflow.set_tag("access_token_set", "true" if settings.access_token else "false")
        if commit_hash:
            mlflow.set_tag("eval_code_git_sha", commit_hash)
        if backend_config:
            backend_git = backend_config.get("infra", {}).get("git_sha")
            if backend_git:
                mlflow.set_tag("backend_git_sha", backend_git)
        
        # =================================================================
        # MLflow Params - Dataset
        # =================================================================
        mlflow.log_param("dataset_name", dataset_manifest["dataset_name"])
        mlflow.log_param("dataset_sha256", dataset_manifest["dataset_sha256"])
        mlflow.log_param("dataset_num_examples", dataset_manifest["dataset_num_examples"])
        mlflow.log_param("dataset_schema_version", DATASET_SCHEMA_VERSION)
        mlflow.log_param("eval_schema_version", EVAL_SCHEMA_VERSION)
        mlflow.log_param("eval_harness_version", EVAL_HARNESS_VERSION)
        
        if commit_hash:
            mlflow.log_param("eval_code_git_sha", commit_hash)
        
        # =================================================================
        # MLflow Params - Backend Config
        # =================================================================
        if backend_config:
            backend_sha = compute_sha256(backend_config)
            mlflow.log_param("backend_config_sha256", backend_sha)
            
            retrieval = backend_config.get("retrieval", {})
            generation = backend_config.get("generation", {})
            prompt = backend_config.get("prompt", {})
            infra = backend_config.get("infra", {})
            
            # Retrieval params (A: Fix embedding naming)
            mlflow.log_param("embedding_model", retrieval.get("embedding_model"))
            mlflow.log_param("embedding_dim", retrieval.get("embedding_dim"))
            # embedding_id: prefer explicit id, else collection, else model
            embedding_id = (
                retrieval.get("embedding_id") or
                infra.get("qdrant_collection") or
                retrieval.get("embedding_model")
            )
            mlflow.log_param("embedding_id", embedding_id)
            mlflow.log_param("dense_k", retrieval.get("dense_k"))
            mlflow.log_param("per_doc_limit", retrieval.get("per_doc_limit"))
            mlflow.log_param("rerank_enabled", retrieval.get("rerank_enabled"))
            mlflow.log_param("rerank_top_n", retrieval.get("rerank_top_n"))
            mlflow.log_param("mmr_enabled", retrieval.get("mmr_enabled"))
            mlflow.log_param("mmr_lambda", retrieval.get("mmr_lambda"))
            
            # Generation params (B: Add missing knobs)
            mlflow.log_param("llm_model", generation.get("model"))
            mlflow.log_param("llm_provider", generation.get("provider"))
            mlflow.log_param("temperature", generation.get("temperature"))
            mlflow.log_param("top_p", generation.get("top_p"))
            mlflow.log_param("max_tokens", generation.get("max_tokens"))
            mlflow.log_param("timeout_seconds", generation.get("timeout_seconds"))
            mlflow.log_param("api_base", generation.get("api_base"))
            
            # Prompt params
            mlflow.log_param("prompt_sha256", prompt.get("prompt_sha256"))
            mlflow.log_param("citation_extraction_enabled", prompt.get("citation_extraction_enabled"))
            
            # Infra params
            mlflow.log_param("app_env", infra.get("app_env"))
            mlflow.log_param("qdrant_collection", infra.get("qdrant_collection"))
            mlflow.log_param("backend_git_sha", infra.get("git_sha"))
            mlflow.log_param("ml_service_url", infra.get("ml_service_url"))
            mlflow.log_param("ml_service_timeout", infra.get("ml_service_timeout"))
        
        # Run config sha
        run_config_sha = compute_sha256(run_config)
        mlflow.log_param("run_config_sha256", run_config_sha)
        
        # Log environment
        log_environment_artifacts()
        
        # Log dataset
        mlflow.log_artifact(dataset_path, "dataset")
        
        # Log dataset manifest
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="manifest_", delete=False) as f:
            json.dump(dataset_manifest, f, indent=2)
            temp_path = f.name
        mlflow.log_artifact(temp_path, "dataset")
        os.unlink(temp_path)
        
        # Log backend config
        if backend_config:
            with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="backend_config_", delete=False) as f:
                json.dump(backend_config, f, indent=2)
                temp_path = f.name
            mlflow.log_artifact(temp_path, "config")
            os.unlink(temp_path)
        
        # Log run config
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="run_config_", delete=False) as f:
            json.dump(run_config, f, indent=2)
            temp_path = f.name
        mlflow.log_artifact(temp_path, "config")
        os.unlink(temp_path)
        
        # Log run manifest
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="run_manifest_", delete=False) as f:
            json.dump(run_manifest, f, indent=2)
            temp_path = f.name
        mlflow.log_artifact(temp_path, "")
        os.unlink(temp_path)
        
        # =================================================================
        # Log Prompt Templates (D: reviewer-proof prompt versioning)
        # =================================================================
        prompt_paths = [
            ("chat_prompt.yaml", "backend/ai/prompts/chat_prompt.yaml"),
            ("citation_prompt.yaml", "backend/ai/prompts/citation_prompt.yaml"),
        ]
        for prompt_name, rel_path in prompt_paths:
            # Try relative to eval, then relative to cwd
            for base in [Path(__file__).parent.parent, Path.cwd()]:
                prompt_path = base / rel_path
                if prompt_path.exists():
                    mlflow.log_artifact(str(prompt_path), "config/prompts")
                    logger.debug(f"Logged prompt template: {prompt_name}")
                    break
        
        # Log ARTIFACTS_README.md
        artifacts_readme = """# MLflow Artifacts Guide

## Artifact Locations

| Artifact | Path | Description |
|----------|------|-------------|
| **Dataset Manifest** | `dataset/manifest_*.json` | Dataset SHA256, schema version, counts |
| **Backend Config** | `config/backend_config_*.json` | Runtime config snapshot (source of truth) |
| **Run Config** | `config/run_config_*.json` | Consolidated eval + backend config |
| **Prompt Templates** | `config/prompts/` | Chat and citation prompt YAML files |
| **Per-Example Forensics** | `examples/examples_*.jsonl` | Query, answer, citations, retrieval, trace |
| **Slice Metrics** | `metrics/slice_metrics_*.json` | Breakdown by language, doc_type, OCR |
| **Metrics Summary** | `metrics/metrics_summary_*.json` | Aggregated metrics + worst examples |
| **Top Failures** | `failures/top_failures_*.jsonl` | Top 20 failures with reason codes |
| **Environment** | `env/` | Python version, pip freeze |

## Reproduction

1. Download `dataset/` folder (contains original dataset + manifest)
2. Use `config/run_config_*.json` for settings
3. Verify with `backend_config_sha256` and `run_config_sha256` params
"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", prefix="ARTIFACTS_README_", delete=False) as f:
            f.write(artifacts_readme)
            temp_path = f.name
        mlflow.log_artifact(temp_path, "config")
        os.unlink(temp_path)
        
        
        # Evaluate each case
        for i, test_case in enumerate(test_cases):
            logger.info(f"Progress: {i + 1}/{len(test_cases)}")

            metrics, example = evaluate_single_case(client, test_case, settings)
            all_metrics.append(metrics)
            all_examples.append(example)
        
        # Aggregate
        aggregated = aggregate_metrics(all_metrics)
        mlflow.log_metrics(aggregated)
        
        # Log examples.jsonl
        examples_path = save_jsonl_artifact(all_examples, "examples_", settings.compress_artifacts)
        mlflow.log_artifact(examples_path, "examples")
        os.unlink(examples_path)
        
        # Log results
        for fmt in ["jsonl", "csv"]:
            path = save_results_artifact(all_metrics, fmt)
            mlflow.log_artifact(path, "results")
            os.unlink(path)
        
        # Slice metrics
        slice_metrics = compute_slice_metrics(all_metrics, all_examples)
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="slice_metrics_", delete=False) as f:
            json.dump(slice_metrics, f, indent=2)
            mlflow.log_artifact(f.name, "metrics")
            os.unlink(f.name)
        
        # Metrics summary
        metrics_summary = create_metrics_summary(all_metrics, all_examples)
        with tempfile.NamedTemporaryFile("w", suffix=".json", prefix="metrics_summary_", delete=False) as f:
            json.dump(metrics_summary, f, indent=2)
            mlflow.log_artifact(f.name, "metrics")
            os.unlink(f.name)
        
        # Top failures
        failures = get_top_failures(all_metrics, all_examples)
        failures_path = save_jsonl_artifact(failures, "top_failures_")
        mlflow.log_artifact(failures_path, "failures")
        os.unlink(failures_path)
        
        run_id = mlflow.active_run().info.run_id
        logger.info(f"Evaluation complete. Run ID: {run_id}")
    
    client.close()
    
    return {
        "run_id": run_id,
        "aggregated_metrics": aggregated,
        "num_cases": len(all_metrics),
        "num_errors": sum(1 for m in all_metrics if m.error),
    }


# =============================================================================
# Dry Run
# =============================================================================
def run_eval_dry(dataset_path: str, settings: EvalSettings) -> List[EvalTestCase]:
    """Dry run - validate dataset without running evaluation."""
    logger.info(f"Dry run: validating {dataset_path}")
    test_cases = load_dataset(dataset_path)

    logger.info(f"Dry run complete. {len(test_cases)} valid test cases.")
    return test_cases
