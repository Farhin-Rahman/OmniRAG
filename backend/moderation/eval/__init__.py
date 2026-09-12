"""Offline evaluation for the moderation pipeline.

Not part of the pytest suite: this makes real LLM calls and measures
judgment quality, not code correctness. Run it by hand
(`python -m moderation.eval.run_eval`) when the prompts or the pipeline
change, to check the recommendations still line up with a known-good set
of labelled campaigns.
"""
