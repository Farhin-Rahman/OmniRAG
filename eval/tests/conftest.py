"""
Pytest configuration for eval tests.

Defines fixtures and markers for evaluation testing.
"""

import os
import pytest


def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (requires running backend)",
    )


@pytest.fixture
def sample_test_case():
    """Provide a sample test case for testing."""
    from eval.dataset import EvalTestCase
    
    return EvalTestCase(
        id="test_fixture_001",
        query="What is the company policy on remote work?",
        golden_docs=["HR_Policy.pdf", "Remote_Work_Guidelines.pdf"],
        golden_answer="Employees may work remotely up to 3 days per week with manager approval.",
        tags=["hr", "policy", "remote"],
    )


@pytest.fixture
def sample_chat_response():
    """Provide a sample chat response for testing."""
    from eval.client import ChatEvalResponse, Source
    
    return ChatEvalResponse(
        answer="Based on the company policy, employees can work remotely up to 3 days per week.",
        sources=[
            Source(
                chunk_id="chunk-001",
                doc_id="doc-001",
                doc_name="HR_Policy.pdf",
                text="Remote work policy allows employees to work from home...",
                page=5,
                score=0.92,
                metadata={"doc_name": "HR_Policy.pdf"},
                raw={},
            ),
            Source(
                chunk_id="chunk-002",
                doc_id="doc-002",
                doc_name="Remote_Work_Guidelines.pdf",
                text="Guidelines for remote work arrangements...",
                page=1,
                score=0.88,
                metadata={"doc_name": "Remote_Work_Guidelines.pdf"},
                raw={},
            ),
        ],
        citations=[],
        trace_id="trace-fixture-001",
        session_id="session-fixture-001",
        conversation_id="conv-fixture-001",
        http_latency_ms=350.0,
        raw_response={},
    )


@pytest.fixture
def sample_trace():
    """Provide a sample trace for testing."""
    return {
        "trace_id": "trace-fixture-001",
        "query_id": "query-fixture-001",
        "steps": [
            {"step": "chat_request_received", "lat_ms": 0, "t": "2025-01-01T00:00:00Z"},
            {"step": "conversation_history_loaded", "lat_ms": 5, "t": "2025-01-01T00:00:00.005Z"},
            {"step": "query_embedding_generated", "lat_ms": 45, "t": "2025-01-01T00:00:00.050Z"},
            {"step": "vector_search_completed", "lat_ms": 120, "t": "2025-01-01T00:00:00.170Z"},
            {"step": "llm_response_generated", "lat_ms": 180, "t": "2025-01-01T00:00:00.350Z"},
            {"step": "messages_persisted", "lat_ms": 355, "t": "2025-01-01T00:00:00.355Z"},
        ],
        "tools_used": ["embedding_service", "qdrant_search", "llm_client"],
        "citations": [],
        "agent_plan": {"variant": "chat_service", "swarm": False},
        "version": 1,
    }


@pytest.fixture
def eval_settings():
    """Provide test evaluation settings."""
    from eval.config import EvalSettings
    
    return EvalSettings(
        backend_url="http://localhost:8081",
        access_token="test-jwt-token",
        experiment_name="test_experiment",
        enable_llm_eval=False,  # Disable for unit tests
    )


@pytest.fixture
def mock_omnirag_client(sample_chat_response, sample_trace):
    """Provide a mocked OmniRAGClient."""
    from unittest.mock import MagicMock
    from eval.client import OmniRAGClient
    
    mock_client = MagicMock(spec=OmniRAGClient)
    mock_client.chat.return_value = sample_chat_response
    mock_client.get_trace.return_value = sample_trace
    mock_client.health_check.return_value = True
    
    return mock_client
