"""Unit tests for extract_json_object.

The cases that matter are the ones a greedy `{.*}` regex got wrong: a
model that emits valid JSON and then keeps talking, or wraps it in prose.
"""

from moderation.json_extract import extract_json_object


class TestExtractJsonObject:
    def test_plain_object(self):
        assert extract_json_object('{"risk_score": 0.2}') == {"risk_score": 0.2}

    def test_trailing_prose_after_object(self):
        raw = '{"risk_score": 0.2, "recommended_action": "APPROVE"} This looks fine to me.'
        assert extract_json_object(raw) == {
            "risk_score": 0.2,
            "recommended_action": "APPROVE",
        }

    def test_second_object_after_first_is_ignored(self):
        raw = '{"risk_score": 0.2} \n\n Note: {"unrelated": true}'
        assert extract_json_object(raw) == {"risk_score": 0.2}

    def test_prose_prefix_before_object(self):
        raw = 'Here is my assessment: {"risk_score": 0.3, "recommended_action": "ESCALATE"}'
        assert extract_json_object(raw) == {
            "risk_score": 0.3,
            "recommended_action": "ESCALATE",
        }

    def test_no_object_returns_none(self):
        assert extract_json_object("no json at all here") is None

    def test_empty_string_returns_none(self):
        assert extract_json_object("") is None

    def test_json_array_not_treated_as_object(self):
        assert extract_json_object("[1, 2, 3]") is None
