#!/usr/bin/env python3
"""
Generate demo evaluation dataset from processed documents.

This script creates a high-quality evaluation dataset for the OmniRAG RAG system
by generating queries based on the documents that have been ingested.

Usage:
    python eval/tools/make_demo_dataset.py
    python eval/tools/make_demo_dataset.py --count 20
    python eval/tools/make_demo_dataset.py --interactive
    python eval/tools/make_demo_dataset.py --list-docs

Examples:
    # Generate 20 queries with auto-detected golden docs
    python eval/tools/make_demo_dataset.py -n 20

    # Interactive mode to manually verify/edit golden docs
    python eval/tools/make_demo_dataset.py --interactive

    # List all processed documents
    python eval/tools/make_demo_dataset.py --list-docs
"""

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Default tenant for OmniRAG (from TEAM_SETUP_INSTRUCTIONS.txt)
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


# ============================================================================
# CURATED QUERY TEMPLATES
# Each query is designed to test specific retrieval and generation capabilities
# ============================================================================

CURATED_QUERIES: List[Dict[str, Any]] = [
    # =========== POLICY QUERIES (English) ===========
    {
        "id": "policy-en-001",
        "query": "What is the organization's user policy?",
        "golden_docs": ["User Policies- سياسات المستخدم.pdf"],
        "category": "policy",
        "difficulty": "easy",
        "language": "en",
    },
    {
        "id": "policy-en-002",
        "query": "What are the guidelines for acceptable use of company systems?",
        "golden_docs": ["سياسة الاستخدام المقبول - Acceptable Use Policy.docx"],
        "category": "policy",
        "difficulty": "easy",
        "language": "en",
    },
    {
        "id": "policy-en-003",
        "query": "What restrictions exist in the user policy regarding data handling?",
        "golden_docs": ["User Policies- سياسات المستخدم.pdf"],
        "category": "policy",
        "difficulty": "medium",
        "language": "en",
    },
    {
        "id": "policy-en-004",
        "query": "Explain the acceptable use policy for email and internet",
        "golden_docs": ["سياسة الاستخدام المقبول - Acceptable Use Policy.docx"],
        "category": "policy",
        "difficulty": "medium",
        "language": "en",
    },
    # =========== POLICY QUERIES (Arabic) ===========
    {
        "id": "policy-ar-001",
        "query": "ما هي سياسة المستخدم في المنظمة؟",
        "golden_docs": ["User Policies- سياسات المستخدم.pdf"],
        "category": "policy",
        "difficulty": "easy",
        "language": "ar",
    },
    {
        "id": "policy-ar-002",
        "query": "ما هي سياسة الاستخدام المقبول؟",
        "golden_docs": ["سياسة الاستخدام المقبول - Acceptable Use Policy.docx"],
        "category": "policy",
        "difficulty": "easy",
        "language": "ar",
    },
    {
        "id": "policy-ar-003",
        "query": "ما هي القيود المفروضة على استخدام أنظمة الشركة؟",
        "golden_docs": [
            "User Policies- سياسات المستخدم.pdf",
            "سياسة الاستخدام المقبول - Acceptable Use Policy.docx",
        ],
        "category": "policy",
        "difficulty": "medium",
        "language": "ar",
    },
    # =========== PROCUREMENT / FIREWALL QUERIES ===========
    {
        "id": "firewall-001",
        "query": "What are the firewall specifications in the purchase order?",
        "golden_docs": ["4100000645-Khedmat- Firewall.pdf"],
        "category": "procurement",
        "difficulty": "easy",
        "language": "en",
    },
    {
        "id": "firewall-002",
        "query": "What is the total price with VAT for the firewall purchase?",
        "golden_docs": ["4100000645-Khedmat- Firewall.pdf"],
        "category": "procurement",
        "difficulty": "medium",
        "language": "en",
    },
    {
        "id": "firewall-003",
        "query": "Who is the vendor for the Khedmat firewall?",
        "golden_docs": ["4100000645-Khedmat- Firewall.pdf"],
        "category": "procurement",
        "difficulty": "easy",
        "language": "en",
    },
    # =========== QUOTATION QUERIES ===========
    {
        "id": "quote-001",
        "query": "What is the total amount in quotation QT-000900?",
        "golden_docs": ["QT-000900.pdf"],
        "category": "quotation",
        "difficulty": "easy",
        "language": "en",
    },
    {
        "id": "quote-002",
        "query": "What items are included in the QT-000900 quote?",
        "golden_docs": ["QT-000900.pdf"],
        "category": "quotation",
        "difficulty": "medium",
        "language": "en",
    },
    # =========== CYBERSECURITY QUERIES ===========
    {
        "id": "cyber-001",
        "query": "What does the cybersecurity scan report show?",
        "golden_docs": ["Cybersecurity Scan.pdf"],
        "category": "cybersecurity",
        "difficulty": "easy",
        "language": "en",
    },
    {
        "id": "cyber-002",
        "query": "What vulnerabilities or issues were identified in the security scan?",
        "golden_docs": ["Cybersecurity Scan.pdf"],
        "category": "cybersecurity",
        "difficulty": "medium",
        "language": "en",
    },
    # =========== SAP / TECHNICAL QUERIES ===========
    {
        "id": "sap-001",
        "query": "What is covered in the ECC implementation guide?",
        "golden_docs": ["5- (ECC) Implementation Guide.pdf"],
        "category": "technical",
        "difficulty": "easy",
        "language": "en",
    },
    {
        "id": "sap-002",
        "query": "What does the SOC 1 Type 2 report cover for SAP ERP?",
        "golden_docs": ["4- SOC 1 Type 2 SAP ERP.pdf"],
        "category": "compliance",
        "difficulty": "medium",
        "language": "en",
    },
    {
        "id": "archive-001",
        "query": "What is the archiving policy and procedure?",
        "golden_docs": ["3-8- Archivig.pdf"],
        "category": "technical",
        "difficulty": "easy",
        "language": "en",
    },
    # =========== CROSS-DOCUMENT QUERIES (harder) ===========
    {
        "id": "cross-001",
        "query": "What security and compliance documents are available?",
        "golden_docs": [
            "Cybersecurity Scan.pdf",
            "4- SOC 1 Type 2 SAP ERP.pdf",
            "User Policies- سياسات المستخدم.pdf",
        ],
        "category": "cross-document",
        "difficulty": "hard",
        "language": "en",
    },
    {
        "id": "cross-002",
        "query": "List all procurement and quotation documents",
        "golden_docs": ["4100000645-Khedmat- Firewall.pdf", "QT-000900.pdf"],
        "category": "cross-document",
        "difficulty": "hard",
        "language": "en",
    },
    # =========== EDGE CASES ===========
    {
        "id": "edge-001",
        "query": "What is the INFO report about?",
        "golden_docs": [
            "INFO_2025_Apr_1.pdf",
            "INFO_2025_Apr_2.pdf",
            "INFO_2025_Apr_3.pdf",
        ],
        "category": "general",
        "difficulty": "medium",
        "language": "en",
    },
]


def load_processed_docs(batch_processed_path: Path) -> Dict[str, dict]:
    """Load the batch-processed.json to get list of indexed documents."""
    if not batch_processed_path.exists():
        print(f"Warning: {batch_processed_path} not found", file=sys.stderr)
        return {}

    with open(batch_processed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_golden_docs(
    queries: List[Dict[str, Any]], processed_docs: Dict[str, dict]
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Validate that golden_docs exist in processed documents.
    Returns validated queries and list of warnings.
    """
    warnings = []
    validated = []
    doc_names = set(processed_docs.keys())

    for query in queries:
        valid_golden = []
        for doc in query.get("golden_docs", []):
            if doc in doc_names:
                valid_golden.append(doc)
            else:
                warnings.append(f"Query '{query['id']}': golden_doc '{doc}' not found")

        if valid_golden or not query.get("golden_docs"):
            query_copy = query.copy()
            query_copy["golden_docs"] = valid_golden
            validated.append(query_copy)
        else:
            warnings.append(f"Query '{query['id']}': no valid golden_docs, skipping")

    return validated, warnings


def select_queries(
    all_queries: List[Dict[str, Any]],
    count: int,
    categories: Optional[List[str]] = None,
    languages: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Select a balanced subset of queries.

    Ensures diversity across categories, difficulties, and languages.
    """
    filtered = all_queries

    if categories:
        filtered = [q for q in filtered if q.get("category") in categories]

    if languages:
        filtered = [q for q in filtered if q.get("language") in languages]

    if len(filtered) <= count:
        return filtered

    # Stratified sampling by category
    by_category: Dict[str, List[dict]] = {}
    for q in filtered:
        cat = q.get("category", "general")
        by_category.setdefault(cat, []).append(q)

    selected = []
    categories_list = list(by_category.keys())
    per_category = max(1, count // len(categories_list))

    for cat in categories_list:
        cat_queries = by_category[cat]
        random.shuffle(cat_queries)
        selected.extend(cat_queries[:per_category])

    # Fill remaining
    remaining = [q for q in filtered if q not in selected]
    random.shuffle(remaining)
    while len(selected) < count and remaining:
        selected.append(remaining.pop())

    return selected[:count]


def interactive_labeling(
    queries: List[Dict[str, Any]], processed_docs: Dict[str, dict]
) -> List[Dict[str, Any]]:
    """Interactively prompt user to confirm/edit golden docs."""
    doc_names = list(processed_docs.keys())

    print("\n" + "=" * 60)
    print("INTERACTIVE GOLDEN DOC LABELING")
    print("=" * 60)
    print(f"\nAvailable documents ({len(doc_names)}):")
    for i, name in enumerate(doc_names, 1):
        # Truncate long names for display
        display_name = name[:50] + "..." if len(name) > 50 else name
        print(f"  {i:2}. {display_name}")
    print()
    print("For each query, enter:")
    print("  - Numbers (comma-separated) to set golden docs")
    print("  - Press Enter to accept auto-detected")
    print("  - 's' to skip this query")
    print("  - 'q' to quit and save current progress")
    print()

    result = []
    for i, item in enumerate(queries, 1):
        print(f"\n[{i}/{len(queries)}] ID: {item['id']}")
        print(f"  Query: {item['query']}")
        print(f"  Category: {item.get('category', 'N/A')} | Lang: {item.get('language', 'N/A')}")
        current = item.get("golden_docs", [])
        print(f"  Auto-detected golden_docs: {current if current else '(none)'}")

        user_input = input("  > Your choice: ").strip()

        if user_input.lower() == "q":
            print("Saving current progress...")
            break
        elif user_input.lower() == "s":
            print("  Skipped")
            continue
        elif user_input:
            try:
                indices = [int(x.strip()) - 1 for x in user_input.split(",")]
                item["golden_docs"] = [
                    doc_names[idx] for idx in indices if 0 <= idx < len(doc_names)
                ]
                print(f"  Updated: {item['golden_docs']}")
            except (ValueError, IndexError):
                print("  Invalid input, keeping auto-detected")

        result.append(item)

    return result


def write_dataset(
    queries: List[Dict[str, Any]],
    output_path: Path,
    tenant_id: str,
) -> None:
    """Write queries to JSONL format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for item in queries:
            test_case = {
                "id": item["id"],
                "query": item["query"],
                "tenant_id": tenant_id,
            }

            # Only include non-empty golden_docs
            if item.get("golden_docs"):
                test_case["golden_docs"] = item["golden_docs"]

            # Include optional fields
            if item.get("golden_answer"):
                test_case["golden_answer"] = item["golden_answer"]

            # Tags from category and language
            tags = []
            if item.get("category"):
                tags.append(item["category"])
            if item.get("language"):
                tags.append(item["language"])
            if item.get("difficulty"):
                tags.append(item["difficulty"])
            if tags:
                test_case["tags"] = tags

            f.write(json.dumps(test_case, ensure_ascii=False) + "\n")

    print(f"\n✓ Wrote {len(queries)} test cases to {output_path}")


def list_documents(processed_docs: Dict[str, dict]) -> None:
    """List all processed documents with details."""
    print("\n" + "=" * 70)
    print("PROCESSED DOCUMENTS")
    print("=" * 70)

    for i, (name, info) in enumerate(processed_docs.items(), 1):
        size_kb = info.get("size", 0) / 1024
        processed_at = info.get("processed_at", "N/A")[:10]
        print(f"{i:2}. {name}")
        print(f"    Size: {size_kb:.1f} KB | Processed: {processed_at}")

    print(f"\nTotal: {len(processed_docs)} documents")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate demo evaluation dataset from processed documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python eval/tools/make_demo_dataset.py -n 20
  python eval/tools/make_demo_dataset.py --interactive
  python eval/tools/make_demo_dataset.py --list-docs
        """,
    )
    parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=20,
        help="Number of queries to generate (default: 20)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="eval/datasets/demo.jsonl",
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--tenant-id",
        "-t",
        type=str,
        default=DEFAULT_TENANT_ID,
        help="Tenant ID to use for all test cases",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive mode to confirm/edit golden docs",
    )
    parser.add_argument(
        "--list-docs",
        action="store_true",
        help="List all processed documents and exit",
    )
    parser.add_argument(
        "--batch-processed",
        type=str,
        default="data/batch-processed.json",
        help="Path to batch-processed.json",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        action="append",
        help="Filter by category (can specify multiple)",
    )
    parser.add_argument(
        "--language",
        "-l",
        type=str,
        action="append",
        help="Filter by language (en, ar)",
    )

    args = parser.parse_args()

    # Find project root
    script_path = Path(__file__).resolve()
    # Handle both direct execution and module execution
    if script_path.parent.name == "tools":
        project_root = script_path.parent.parent.parent  # eval/tools -> eval -> root
    else:
        project_root = Path.cwd()

    batch_processed_path = project_root / args.batch_processed
    output_path = project_root / args.output

    # Load processed docs
    processed_docs = load_processed_docs(batch_processed_path)
    if not processed_docs:
        print(
            f"Error: No processed documents found at {batch_processed_path}",
            file=sys.stderr,
        )
        print("Run batch ingestion first: POST /ingest/batch", file=sys.stderr)
        return 1

    print(f"✓ Loaded {len(processed_docs)} processed documents")

    # List docs mode
    if args.list_docs:
        list_documents(processed_docs)
        return 0

    # Validate golden docs against actual processed docs
    queries, warnings = validate_golden_docs(CURATED_QUERIES, processed_docs)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings[:10]:
            print(f"  - {w}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")

    print(f"✓ {len(queries)} queries with valid golden docs")

    # Select queries
    selected = select_queries(
        queries,
        count=args.count,
        categories=args.category,
        languages=args.language,
    )
    print(f"✓ Selected {len(selected)} queries")

    # Interactive mode
    if args.interactive:
        selected = interactive_labeling(selected, processed_docs)

    if not selected:
        print("No queries to write", file=sys.stderr)
        return 1

    # Write output
    write_dataset(selected, output_path, args.tenant_id)

    # Print summary
    print("\n" + "=" * 60)
    print("DATASET SUMMARY")
    print("=" * 60)
    categories = {}
    languages = {}
    for q in selected:
        cat = q.get("category", "unknown")
        lang = q.get("language", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
        languages[lang] = languages.get(lang, 0) + 1

    print(f"Total queries: {len(selected)}")
    print(f"By category: {dict(sorted(categories.items()))}")
    print(f"By language: {dict(sorted(languages.items()))}")
    print(f"\nOutput: {output_path}")
    print("\nNext steps:")
    print("  1. Review the dataset: cat eval/datasets/demo.jsonl")
    print("  2. Run evaluation: python -m eval --dataset eval/datasets/demo.jsonl")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())

