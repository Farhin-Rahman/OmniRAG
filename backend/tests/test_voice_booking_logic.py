"""Unit tests for the voice agent's booking-field validation.

This is the logic that was found to have a real gap during manual testing:
the model captures a vague address like "somewhere near downtown" verbatim
(correct — no hallucinated fake address) but doesn't reliably flag it as
missing on its own. _missing_booking_fields() is the independent check that
catches that. Covered here so the fix stays fixed.
"""

import asyncio
import json

import routes.voice as voice_module
from routes.voice import (
    _has_street_number,
    _merge_booking_fields,
    _missing_booking_fields,
    _spoken_digits_to_numerals,
)


def _intent(**overrides) -> dict:
    base = {
        "intent": "book_appointment",
        "service": "furnace repair",
        "address": "142 Maple Crescent, Calgary, AB",
        "phone": "4035551234",
        "customer_name": "Jane Doe",
        "preferred_day": None,
        "preferred_time": None,
        "missing_fields": [],
    }
    base.update(overrides)
    return base


class TestMissingBookingFields:
    def test_complete_intent_has_nothing_missing(self):
        assert _missing_booking_fields(_intent()) == []

    def test_null_address_is_missing(self):
        assert "address" in _missing_booking_fields(_intent(address=None))

    def test_vague_address_with_no_digit_is_treated_as_missing(self):
        # The model captured this verbatim rather than inventing a fake
        # precise address — correct — but it isn't usable for dispatch.
        intent = _intent(address="Maple street somewhere near downtown")
        assert "address" in _missing_booking_fields(intent)

    def test_real_street_address_is_not_flagged(self):
        intent = _intent(address="142 Maple Crescent in Calgary")
        assert "address" not in _missing_booking_fields(intent)

    def test_missing_phone(self):
        assert "phone" in _missing_booking_fields(_intent(phone=None))

    def test_missing_customer_name(self):
        assert "customer_name" in _missing_booking_fields(_intent(customer_name=None))

    def test_missing_service(self):
        assert "service" in _missing_booking_fields(_intent(service=None))

    def test_does_not_trust_model_self_reported_missing_fields(self):
        # missing_fields says nothing's missing, but address is null —
        # independent verification should catch it anyway.
        intent = _intent(address=None, missing_fields=[])
        assert "address" in _missing_booking_fields(intent)

    def test_preferred_day_and_time_are_never_required(self):
        intent = _intent(preferred_day=None, preferred_time=None)
        assert _missing_booking_fields(intent) == []


class TestSpokenNumbers:
    """Retell's speech-to-text returns numbers as words, not digits. A digit-
    only check rejected real addresses forever (the caller said "four five two
    one McEwan Road" and the agent kept asking for the address)."""

    def test_spoken_digit_run_becomes_numerals(self):
        assert (
            _spoken_digits_to_numerals("four five two one McEwan Road, n w Edmonton")
            == "4521 McEwan Road, n w Edmonton"
        )

    def test_spoken_phone_number_becomes_numerals(self):
        spoken = "seven eight zero five five five zero one four two"
        assert _spoken_digits_to_numerals(spoken) == "7805550142"

    def test_a_lone_number_word_is_left_alone(self):
        text = "the one near the mall"
        assert _spoken_digits_to_numerals(text) == text

    def test_spoken_address_counts_as_having_a_street_number(self):
        assert _has_street_number("four five two one McEwan Road, n w Edmonton")

    def test_tens_and_single_leading_number_words_count(self):
        assert _has_street_number("twenty one fifty McEwan Road")
        assert _has_street_number("five McEwan Road")

    def test_vague_locations_still_do_not_count(self):
        assert not _has_street_number("in Edmonton near University of Alberta")
        assert not _has_street_number("somewhere in McEwan")
        assert not _has_street_number("the one near the mall")

    def test_spoken_address_is_not_reported_missing(self):
        intent = _intent(address="four five two one McEwan Road, n w Edmonton")
        assert _missing_booking_fields(intent) == []

    def test_vague_address_is_asked_first(self):
        intent = _intent(address="near downtown", phone=None)
        assert _missing_booking_fields(intent)[0] == "address"


class TestMergeBookingFields:
    def test_a_captured_field_is_not_forgotten_when_the_model_drops_it(self):
        state: dict = {}
        _merge_booking_fields(state, _intent(service="furnace repair", address=None))
        merged = _merge_booking_fields(state, _intent(service=None, address=None))
        assert merged["service"] == "furnace repair"

    def test_a_usable_address_is_not_replaced_by_a_vaguer_one(self):
        state: dict = {}
        _merge_booking_fields(state, _intent(address="142 Maple Crescent, Calgary"))
        merged = _merge_booking_fields(state, _intent(address="near downtown"))
        assert merged["address"] == "142 Maple Crescent, Calgary"

    def test_a_vague_address_is_replaced_by_a_usable_one(self):
        state: dict = {}
        _merge_booking_fields(state, _intent(address="near downtown"))
        merged = _merge_booking_fields(state, _intent(address="142 Maple Crescent"))
        assert merged["address"] == "142 Maple Crescent"

    def test_spoken_digits_are_normalized_when_stored(self):
        merged = _merge_booking_fields(
            {},
            _intent(
                address="four five two one McEwan Road",
                phone="seven eight zero five five five zero one four two",
            ),
        )
        assert merged["address"] == "4521 McEwan Road"
        assert merged["phone"] == "7805550142"


class _FakeSocket:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))


def _run_call(monkeypatch, turns, extractions):
    """Drive _handle_turn like a real call: one caller utterance per turn, with
    the classifier returning scripted (deliberately unreliable) extractions."""
    scripted = iter(extractions)
    booked: list[dict] = []

    async def fake_classify(llm, conversation, message):
        return next(scripted)

    async def fake_webhook(details, call_id):
        booked.append(details)
        return True

    monkeypatch.setattr(voice_module, "_classify_intent", fake_classify)
    monkeypatch.setattr(voice_module, "_trigger_booking_webhook", fake_webhook)
    monkeypatch.setattr(voice_module, "record_booking", lambda **kw: 1)

    socket, state, replies = _FakeSocket(), {}, []
    transcript: list[dict] = []
    for i, utterance in enumerate(turns, start=1):
        transcript.append({"role": "user", "content": utterance})
        before = len(socket.sent)
        event = {"response_id": i, "transcript": transcript}
        asyncio.run(voice_module._handle_turn(socket, None, event, "call-1", state))
        agent_text = "".join(
            m.get("content", "")
            for m in socket.sent[before:]
            if m["response_type"] == "response"
        )
        replies.append(agent_text)
        transcript.append({"role": "agent", "content": agent_text})
    return replies, booked


def _said(**fields) -> dict:
    """An extraction where only the given fields were found this turn."""
    found = {"service": None, "address": None, "phone": None, "customer_name": None}
    found.update(fields)
    return _intent(**found)


class TestBookingConversation:
    def test_the_circling_conversation_now_completes(self, monkeypatch):
        """The real failing call: speech-to-text spells the address out, and the
        model forgets the service it was already told. It must still finish."""
        spoken_phone = "seven eight zero five five five zero one four two"
        turns = [
            "I need to book a furnace repair.",
            "It's four five two one McEwan Road, n w Edmonton.",
            "It's repair.",
            spoken_phone,
            "Jane Smith",
        ]
        extractions = [
            _said(service="furnace repair"),
            _said(address="four five two one McEwan Road, n w Edmonton"),
            _said(service="repair"),
            _said(phone=spoken_phone),
            _said(customer_name="Jane Smith"),
        ]
        replies, booked = _run_call(monkeypatch, turns, extractions)

        assert len(booked) == 1, replies
        assert booked[0]["service"] == "repair"
        assert booked[0]["address"] == "4521 McEwan Road, n w Edmonton"
        assert booked[0]["phone"] == "7805550142"
        assert booked[0]["customer_name"] == "Jane Smith"
        assert replies[-1].startswith("You're all set")
        assert not any("Let me check on that" in r for r in replies)

    def test_it_never_asks_twice_for_something_already_given(self, monkeypatch):
        turns = [
            "I want to book a repair.",
            "It's four five two one McEwan Road.",
            "Jane Smith.",
        ]
        extractions = [
            _said(service="repair"),
            _said(address="four five two one McEwan Road"),
            _said(customer_name="Jane Smith"),
        ]
        replies, _ = _run_call(monkeypatch, turns, extractions)
        assert "address" not in replies[1] and "street number" not in replies[1]
        assert "service" not in replies[1] and "service" not in replies[2]

    def test_a_vague_address_is_reasked_specifically_and_at_once(self, monkeypatch):
        turns = ["I need to book a repair.", "Somewhere in McEwan, Edmonton."]
        extractions = [
            _said(service="repair"),
            _said(address="Somewhere in McEwan, Edmonton"),
        ]
        replies, booked = _run_call(monkeypatch, turns, extractions)
        assert not booked
        assert "street number" in replies[1]
