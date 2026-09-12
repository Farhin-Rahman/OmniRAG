"""Pull one JSON object out of an LLM response.

Every prompt in this package asks for "ONLY compact JSON", but smaller /
cheaper models don't always comply — they emit the object and then keep
talking, or prefix it with "Here is my assessment:". A greedy `{.*}`
regex breaks on that (it grabs a trailing brace and json.loads reports
"Extra data"). json.JSONDecoder().raw_decode parses exactly one value
from the first brace and ignores whatever follows, which is what we want.
"""

import json
from typing import Optional


def extract_json_object(raw: str) -> Optional[dict]:
    """Return the first JSON object in `raw`, or None if there isn't a
    parseable one. Trailing prose or a second object is ignored."""
    if not raw:
        return None
    start = raw.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(raw[start:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None
