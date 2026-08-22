"""
Main entry point for running eval package as a module.

Usage:
    python -m eval --dataset eval/datasets/sample.jsonl
    python -m eval.cli --dataset eval/datasets/sample.jsonl
    python -m eval.runner --dataset eval/datasets/sample.jsonl
"""

from eval.cli import main

if __name__ == "__main__":
    main()

