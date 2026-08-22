"""
Tests for OmniRAG Evaluation Package v2.0.

These tests verify the core functionality of the evaluation pipeline
including: token_f1, reproducibility, privacy controls, LLM judge default,
approx metrics, and redaction.

Run tests:
    pytest eval/tests/test_eval.py -v
"""

import json
import os
import tempfile
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from eval.client import ChatEvalResponse, OmniRAGClient, Source
from eval.config import EvalSettings
from eval.dataset import DatasetLoadError, EvalTestCase, load_dataset
from eval.metrics import (
    PerCaseMetrics,
    aggregate_metrics,
    compute_per_case_metrics,
    compute_retrieval_metrics,
    extract_latency_from_trace,
    compute_token_f1,
    compute_failure_score,
)


# ============================================
# Test Fixtures
# ============================================


@pytest.fixture
def sample_sources() -> List[Source]:
    """Create sample sources for testing."""
    return [
        Source(
            chunk_id="chunk-1",
            doc_id="doc-1",
            doc_name="Policy.pdf",
            text="This is the policy document text.",
            page=1,
            score=0.95,
            metadata={"doc_name": "Policy.pdf"},
            raw={},
        ),
        Source(
            chunk_id="chunk-2",
            doc_id="doc-2",
            doc_name="Handbook.pdf",
            text="This is the handbook text.",
            page=5,
            score=0.85,
            metadata={"doc_name": "Handbook.pdf"},
            raw={},
        ),
    ]


@pytest.fixture
def sample_trace() -> Dict[str, Any]:
    """Create sample trace data for testing."""
    return {
        "trace_id": "trace-123",
        "query_id": "query-456",
        "steps": [
            {"step": "chat_request_received", "lat_ms": 0},
            {"step": "query_embedding_generated", "lat_ms": 50},
            {"step": "vector_search_completed", "lat_ms": 120},
            {"step": "llm_response_generated", "lat_ms": 1500},
            {"step": "messages_persisted", "lat_ms": 1700},
        ],
        "tools_used": ["embedding_service", "qdrant_search", "llm_client"],
        "citations": [],
    }


@pytest.fixture
def sample_chat_response(sample_sources: List[Source]) -> ChatEvalResponse:
    """Create sample chat response for testing."""
    return ChatEvalResponse(
        answer="The policy states that all users must follow guidelines.",
        sources=sample_sources,
        citations=[],
        trace_id="trace-123",
        session_id="session-456",
        conversation_id="conv-789",
        http_latency_ms=2000.0,
        raw_response={},
    )


@pytest.fixture
def sample_test_cases_jsonl() -> str:
    """Create a temporary JSONL file with test cases."""
    content = """{\"id\": \"test-1\", \"query\": \"What is the policy?\", \"golden_docs\": [\"Policy.pdf\"]}
{\"id\": \"test-2\", \"query\": \"Tell me about the handbook\", \"golden_docs\": [\"Handbook.pdf\"], \"golden_answer\": \"The handbook covers...\"}
{\"id\": \"test-3\", \"query\": \"General question without golden docs\"}
"""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    yield path
    os.unlink(path)


# ============================================
# Dataset Tests
# ============================================


class TestDataset:
    """Tests for dataset loading and validation."""

    def test_load_dataset_success(self, sample_test_cases_jsonl: str):
        """Test loading a valid dataset."""
        test_cases = load_dataset(sample_test_cases_jsonl)
        
        assert len(test_cases) == 3
        assert test_cases[0].id == "test-1"
        assert test_cases[0].query == "What is the policy?"
        assert test_cases[0].golden_docs == ["Policy.pdf"]
        assert test_cases[1].golden_answer == "The handbook covers..."
        assert test_cases[2].golden_docs is None
    
    def test_load_dataset_file_not_found(self):
        """Test loading a non-existent file raises error."""
        with pytest.raises(DatasetLoadError, match="not found"):
            load_dataset("nonexistent.jsonl")


# ============================================
# Token F1 Tests (Counter-based)
# ============================================


class TestTokenF1:
    """Tests for Counter-based token F1 computation."""
    
    def test_exact_match(self):
        """Exact match should return 1.0."""
        assert compute_token_f1("hello world", "hello world") == 1.0
    
    def test_handles_duplicates(self):
        """Counter-based should handle duplicates differently from set-based."""
        f1 = compute_token_f1("the the cat", "the cat")
        assert f1 is not None
        assert f1 < 1.0  # Set-based would give 1.0
    
    def test_partial_overlap(self):
        """Partial overlap should give score between 0 and 1."""
        f1 = compute_token_f1("hello world", "hello there")
        assert f1 is not None
        assert 0 < f1 < 1
    
    def test_both_empty(self):
        """Both empty strings should return 1.0 (perfect match)."""
        assert compute_token_f1("", "") == 1.0
    
    def test_predicted_empty_expected_nonempty(self):
        """Empty predicted, non-empty expected should return 0.0."""
        assert compute_token_f1("", "hello world") == 0.0
    
    def test_predicted_nonempty_expected_empty(self):
        """Non-empty predicted, empty expected should return 0.0."""
        assert compute_token_f1("hello world", "") == 0.0
    
    def test_punctuation_only(self):
        """Punctuation-only strings normalize to empty, return 1.0."""
        assert compute_token_f1("!!!", "???") == 1.0
    
    def test_punctuation_vs_text(self):
        """Punctuation-only vs text should return 0.0."""
        assert compute_token_f1("!!!", "hello") == 0.0


# ============================================
# Reproducibility Tests
# ============================================


class TestReproducibility:
    """Tests for deterministic hashing and reproducibility."""
    
    def test_canonical_json_deterministic(self):
        """Canonical JSON should be deterministic."""
        from eval.config import canonical_json, compute_sha256
        
        obj = {"b": 2, "a": {"d": 4, "c": 3}}
        json1 = canonical_json(obj)
        json2 = canonical_json(obj)
        assert json1 == json2
        
        sha1 = compute_sha256(obj)
        sha2 = compute_sha256(obj)
        assert sha1 == sha2
    
    def test_canonical_json_sorts_keys(self):
        """Canonical JSON must sort keys."""
        from eval.config import canonical_json
        
        obj1 = {"b": 1, "a": 2}
        obj2 = {"a": 2, "b": 1}
        assert canonical_json(obj1) == canonical_json(obj2)
    
    def test_dataset_sha256_from_bytes(self, sample_test_cases_jsonl: str):
        """Dataset SHA256 should be computed from file bytes."""
        from eval.runner import create_dataset_manifest
        
        test_cases = load_dataset(sample_test_cases_jsonl)
        manifest1 = create_dataset_manifest(sample_test_cases_jsonl, test_cases)
        manifest2 = create_dataset_manifest(sample_test_cases_jsonl, test_cases)
        
        assert manifest1["dataset_sha256"] == manifest2["dataset_sha256"]
        assert len(manifest1["dataset_sha256"]) == 64  # SHA256 hex


# ============================================
# Redaction Tests
# ============================================


class TestRedaction:
    """Tests for PII redaction."""
    
    def test_redact_email(self):
        """Email addresses should be redacted."""
        from eval.utils.redaction import redact_text
        assert "[EMAIL]" in redact_text("Contact john@example.com for help")
    
    def test_redact_phone_us(self):
        """US phone numbers should be redacted."""
        from eval.utils.redaction import redact_text
        assert "[PHONE]" in redact_text("Call 555-123-4567")
    
    def test_redact_long_digits(self):
        """Long digit sequences should be redacted."""
        from eval.utils.redaction import redact_text
        text = "ID: 12345678901234"
        result = redact_text(text)
        assert "[ID]" in result
    
    def test_empty_text_unchanged(self):
        """Empty text should return empty."""
        from eval.utils.redaction import redact_text
        assert redact_text("") == ""


# ============================================
# LLM Judge Default Tests
# ============================================


class TestLLMJudgeDefault:
    """Tests to enforce LLM judge is OFF by default."""
    
    def test_llm_judge_off_by_default_enforced(self):
        """LLM judge is OFF by default and enforced by this test."""
        settings = EvalSettings(
            backend_url="http://test",
            access_token="test-jwt-token",
        )
        assert settings.enable_llm_eval is False
    
    def test_llm_judge_can_be_enabled(self):
        """LLM judge can be explicitly enabled."""
        settings = EvalSettings(
            backend_url="http://test",
            access_token="test-jwt-token",
            enable_llm_eval=True,
        )
        assert settings.enable_llm_eval is True


# ============================================
# Approx Retrieval Metric Tests
# ============================================


class TestApproxMetricPrefix:
    """Tests for approx_ prefix on name-based retrieval metrics."""
    
    def test_name_based_metrics_prefixed(self, sample_sources: List[Source]):
        """Name-based metrics should be prefixed with approx_."""
        metrics, metric_type = compute_retrieval_metrics(
            golden_docs=["Policy.pdf"],
            golden_doc_ids=None,
            retrieved_sources=sample_sources,
        )
        
        assert metric_type == "approx"
        assert "approx_doc_recall" in metrics
        assert "approx_mrr" in metrics
    
    def test_id_based_metrics_not_prefixed(self, sample_sources: List[Source]):
        """ID-based metrics should not have approx_ prefix."""
        metrics, metric_type = compute_retrieval_metrics(
            golden_docs=None,
            golden_doc_ids=["doc-1"],
            retrieved_sources=sample_sources,
        )
        
        assert metric_type == "exact"
        assert "doc_recall" in metrics
        assert "mrr" in metrics


# ============================================
# Failure Score Tests
# ============================================


class TestFailureScore:
    """Tests for failure score computation."""
    
    def test_error_adds_high_score(self):
        """Errors should add 2.0 to failure score."""
        metrics = PerCaseMetrics(id="test-1", error="Some error")
        score, reasons = compute_failure_score(metrics)
        
        assert score >= 2.0
        assert "error" in reasons
    
    def test_missing_metrics_add_penalty(self):
        """Missing metrics should add small penalty and reason code."""
        metrics = PerCaseMetrics(id="test-1")  # No doc_recall or token_f1
        score, reasons = compute_failure_score(metrics)
        
        assert "missing_doc_recall" in reasons
        assert "missing_token_f1" in reasons


# ============================================
# Latency Extraction Tests
# ============================================


class TestLatencyExtraction:
    """Tests for latency extraction from trace."""
    
    def test_extract_latency(self, sample_trace: Dict[str, Any]):
        """Test latency extraction from valid trace."""
        embedding_ms, retrieval_ms, llm_ms, e2e_ms = extract_latency_from_trace(sample_trace)
        
        assert embedding_ms == 50
        assert retrieval_ms == 120
        assert llm_ms == 1500
        assert e2e_ms == 1700
    
    def test_extract_latency_empty_trace(self):
        """Test latency extraction from empty trace."""
        embedding_ms, retrieval_ms, llm_ms, e2e_ms = extract_latency_from_trace(None)
        
        assert embedding_ms is None
        assert retrieval_ms is None


# ============================================
# Metrics Aggregation Tests
# ============================================


class TestMetricsAggregation:
    """Tests for metrics aggregation."""
    
    def test_aggregate_empty_list(self):
        """Aggregating empty list should return minimal result."""
        result = aggregate_metrics([])
        assert result["total_cases"] == 0
    
    def test_aggregate_single_case(self):
        """Aggregating single case should work."""
        metrics = [PerCaseMetrics(id="test-1", doc_recall=0.8, http_latency_ms=1000)]
        result = aggregate_metrics(metrics)
        
        assert result["total_cases"] == 1
        assert result["mean_doc_recall"] == 0.8
        assert result["mean_http_latency_ms"] == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
