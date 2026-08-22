"""
MLflow Runtime Tracing Service.

Provides automatic experiment tracking for chat requests:
- Logs query metadata (model, user, tenant)
- Logs retrieval metrics (chunk count, latency)
- Logs response metrics (generation time, token count estimate)

Usage:
    from services.mlflow_tracing import log_chat_trace

    # At the end of chat() method:
    log_chat_trace(query_id, tenant_id, user_id, steps, sources, response_text)
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from config.settings import settings

logger = logging.getLogger(__name__)

# Lazy import mlflow to avoid startup penalty if not configured
_mlflow = None


def _get_mlflow():
    """Lazy load mlflow to avoid import errors if not installed."""
    global _mlflow
    if _mlflow is None:
        try:
            import mlflow

            _mlflow = mlflow
            # Set tracking URI from settings
            tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
            _mlflow.set_tracking_uri(tracking_uri)
            logger.info(f"MLflow initialized: tracking_uri={tracking_uri}")
        except ImportError:
            logger.warning("MLflow not installed. Tracing disabled.")
            _mlflow = False
    return _mlflow if _mlflow else None


def is_mlflow_enabled() -> bool:
    """Check if MLflow tracing is enabled."""
    return (
        os.getenv("MLFLOW_ENABLED", "true").lower() == "true"
        and _get_mlflow() is not None
    )


def log_chat_trace(
    query_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    steps: List[Dict[str, Any]],
    sources: List[Dict[str, Any]],
    response_text: str,
    handler: str = "doc_rag",
    embedding_model: Optional[str] = None,
    llm_model: Optional[str] = None,
    retrieval_count: int = 0,
    rerank_enabled: bool = False,
) -> Optional[str]:
    """
    Log a chat interaction to MLflow as a run.

    Args:
        query_id: Unique trace ID for this query
        tenant_id: Tenant UUID
        user_id: User UUID
        steps: Pipeline trace steps with latencies
        sources: Retrieved source documents
        response_text: Final LLM response
        handler: Routing handler used (doc_rag, chitchat, block, etc.)
        embedding_model: Embedding model name
        llm_model: LLM model name
        retrieval_count: Number of chunks retrieved
        rerank_enabled: Whether reranking was applied

    Returns:
        MLflow run_id if logged, None otherwise
    """
    mlflow = _get_mlflow()
    if not mlflow or not is_mlflow_enabled():
        return None

    try:
        experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "omnirag_chat_traces")
        mlflow.set_experiment(experiment_name)

        with mlflow.start_run(run_name=f"chat_{query_id}") as run:
            # Log parameters
            mlflow.log_param("query_id", str(query_id))
            mlflow.log_param("tenant_id", str(tenant_id))
            mlflow.log_param("user_id", str(user_id))
            mlflow.log_param("handler", handler)
            mlflow.log_param(
                "embedding_model", embedding_model or settings.embedding_model
            )
            mlflow.log_param("llm_model", llm_model or settings.llm_model)
            mlflow.log_param("rerank_enabled", str(rerank_enabled))

            # Calculate latencies from steps
            total_latency_ms = 0
            embedding_latency_ms = 0
            search_latency_ms = 0
            llm_latency_ms = 0

            for step in steps:
                lat = step.get("lat_ms", 0)
                total_latency_ms += lat
                step_name = step.get("step", "")
                if "embedding" in step_name:
                    embedding_latency_ms = lat
                elif "search" in step_name or "qdrant" in step_name.lower():
                    search_latency_ms = lat
                elif "llm" in step_name or "generation" in step_name:
                    llm_latency_ms = lat

            # Log metrics
            mlflow.log_metric("total_latency_ms", total_latency_ms)
            mlflow.log_metric("embedding_latency_ms", embedding_latency_ms)
            mlflow.log_metric("search_latency_ms", search_latency_ms)
            mlflow.log_metric("llm_latency_ms", llm_latency_ms)
            mlflow.log_metric("retrieval_count", retrieval_count)
            mlflow.log_metric("source_count", len(sources))
            mlflow.log_metric("response_length", len(response_text))

            # Log trace as artifact (JSON)
            import json
            import tempfile

            trace_data = {
                "query_id": str(query_id),
                "steps": steps,
                "sources": [
                    {"doc_id": s.get("doc_id"), "score": s.get("score")}
                    for s in sources
                ],
                "response_length": len(response_text),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as f:
                json.dump(trace_data, f, indent=2)
                trace_path = f.name

            mlflow.log_artifact(trace_path, artifact_path="traces")
            os.unlink(trace_path)

            logger.info(
                f"MLflow trace logged: run_id={run.info.run_id} query_id={query_id}"
            )
            return run.info.run_id

    except Exception as e:
        logger.warning(f"Failed to log MLflow trace: {e}")
        return None
