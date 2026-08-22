"""
Dataset handling for OmniRAG Offline Evaluation.

This module provides data models and loaders for evaluation test cases.
Test cases are stored in JSONL format with one JSON object per line.

Dataset Schema (JSONL):
    Each line should be a JSON object with the following fields:
    {
        "id": "unique-test-id",           # Required: Unique identifier
        "query": "What is the policy?",   # Required: The question to ask
        "tenant_id": "uuid",              # Optional: Metadata only (auth uses JWT access token)
        "golden_answer": "The policy...", # Optional: Expected reference answer
        "golden_docs": ["doc1.pdf"],      # Optional: Expected document names
        "tags": ["policy", "urgent"]      # Optional: Tags for filtering
    }

Example:
    from eval.dataset import load_dataset
    
    test_cases = load_dataset("eval/datasets/sample.jsonl")
    for case in test_cases:
        print(f"Query: {case.query}")
        if case.golden_docs:
            print(f"Expected docs: {case.golden_docs}")
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class EvalTestCase(BaseModel):
    """
    A single evaluation test case.
    
    Represents a query to evaluate against the RAG system, with optional
    golden (expected) answers and documents for computing metrics.
    
    Attributes:
        id: Unique identifier for the test case.
        query: The question/query to send to the RAG system.
        tenant_id: Optional tenant ID metadata for this specific test case.
        golden_answer: Optional reference answer for answer quality metrics.
        golden_docs: Optional list of expected document names for retrieval metrics.
        tags: Optional tags for filtering and categorization.
    """
    
    id: str = Field(..., description="Unique identifier for the test case")
    query: str = Field(..., description="The question to evaluate")
    tenant_id: Optional[str] = Field(
        default=None,
        description="Optional tenant ID metadata for this test case (auth uses JWT)"
    )
    golden_answer: Optional[str] = Field(
        default=None,
        description="Expected reference answer for quality metrics"
    )
    golden_docs: Optional[List[str]] = Field(
        default=None,
        description="Expected document names for retrieval metrics"
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Optional tags for filtering and categorization"
    )

    @field_validator("query")
    @classmethod
    def validate_query_not_empty(cls, v: str) -> str:
        """Ensure query is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("Query cannot be empty")
        return v.strip()

    @field_validator("golden_docs")
    @classmethod
    def normalize_golden_docs(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Normalize golden_docs by stripping whitespace."""
        if v is None:
            return None
        return [doc.strip() for doc in v if doc and doc.strip()]

    model_config = {
        "extra": "ignore",  # Ignore unknown fields for forward compatibility
    }


class DatasetLoadError(Exception):
    """Raised when a dataset fails to load or validate."""
    pass


def load_dataset(path: str) -> List[EvalTestCase]:
    """
    Load evaluation test cases from a JSONL file.
    
    Each line in the file should be a valid JSON object conforming to
    the EvalTestCase schema. Empty lines and lines starting with '#' are skipped.
    
    Args:
        path: Path to the JSONL file containing test cases.
        
    Returns:
        List of validated EvalTestCase objects.
        
    Raises:
        DatasetLoadError: If the file cannot be read or contains invalid data.
        
    Example:
        test_cases = load_dataset("eval/datasets/sample.jsonl")
        print(f"Loaded {len(test_cases)} test cases")
    """
    file_path = Path(path)
    
    if not file_path.exists():
        raise DatasetLoadError(f"Dataset file not found: {path}")
    
    if not file_path.is_file():
        raise DatasetLoadError(f"Path is not a file: {path}")
    
    test_cases: List[EvalTestCase] = []
    errors: List[str] = []
    
    logger.info(f"Loading dataset from {path}")
    
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:  # utf-8-sig handles BOM
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue
                
                try:
                    data = json.loads(line)
                    test_case = EvalTestCase.model_validate(data)
                    test_cases.append(test_case)
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")
                except Exception as e:
                    errors.append(f"Line {line_num}: Validation error - {e}")
    except IOError as e:
        raise DatasetLoadError(f"Failed to read dataset file: {e}")
    
    if errors:
        error_summary = "\n".join(errors[:10])  # Show first 10 errors
        if len(errors) > 10:
            error_summary += f"\n... and {len(errors) - 10} more errors"
        raise DatasetLoadError(f"Dataset validation failed:\n{error_summary}")
    
    if not test_cases:
        raise DatasetLoadError(f"No valid test cases found in {path}")
    
    # Check for duplicate IDs
    seen_ids = set()
    duplicates = []
    for case in test_cases:
        if case.id in seen_ids:
            duplicates.append(case.id)
        seen_ids.add(case.id)
    
    if duplicates:
        logger.warning(f"Duplicate test case IDs found: {duplicates[:5]}")
    
    logger.info(f"Loaded {len(test_cases)} test cases from {path}")
    
    # Log summary statistics
    with_golden_docs = sum(1 for c in test_cases if c.golden_docs)
    with_golden_answer = sum(1 for c in test_cases if c.golden_answer)
    logger.info(
        f"Dataset stats: {with_golden_docs} with golden_docs, "
        f"{with_golden_answer} with golden_answer"
    )
    
    return test_cases


def save_dataset(test_cases: List[EvalTestCase], path: str) -> None:
    """
    Save evaluation test cases to a JSONL file.
    
    Args:
        test_cases: List of EvalTestCase objects to save.
        path: Path to the output JSONL file.
        
    Example:
        save_dataset(test_cases, "eval/datasets/my_dataset.jsonl")
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, "w", encoding="utf-8") as f:
        for case in test_cases:
            f.write(case.model_dump_json() + "\n")
    
    logger.info(f"Saved {len(test_cases)} test cases to {path}")
