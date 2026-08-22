#!/usr/bin/env python3
"""Validate demo dataset loads correctly."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from eval.dataset import load_dataset


def main():
    dataset_path = project_root / "eval" / "datasets" / "demo.jsonl"
    
    print(f"Loading dataset: {dataset_path}")
    try:
        cases = load_dataset(str(dataset_path))
        print(f"✓ Loaded {len(cases)} test cases")
        
        # Summary
        categories = {}
        languages = {}
        with_golden_docs = 0
        
        for case in cases:
            tags = case.tags or []
            for tag in tags:
                if tag in ("en", "ar"):
                    languages[tag] = languages.get(tag, 0) + 1
                elif tag in ("easy", "medium", "hard"):
                    pass
                else:
                    categories[tag] = categories.get(tag, 0) + 1
            if case.golden_docs:
                with_golden_docs += 1
        
        print(f"\nDataset Summary:")
        print(f"  Total cases: {len(cases)}")
        print(f"  With golden_docs: {with_golden_docs}")
        print(f"  Categories: {dict(sorted(categories.items()))}")
        print(f"  Languages: {dict(sorted(languages.items()))}")
        
        print(f"\nSample (first case):")
        print(f"  ID: {cases[0].id}")
        print(f"  Query: {cases[0].query[:50]}...")
        print(f"  Golden docs: {cases[0].golden_docs}")
        
        print("\n✓ Dataset validation passed!")
        return 0
        
    except Exception as e:
        print(f"✗ Failed to load dataset: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

