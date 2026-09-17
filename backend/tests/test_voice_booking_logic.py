"""Unit tests for the voice agent's booking-field validation.

This is the logic that was found to have a real gap during manual testing:
the model captures a vague address like "somewhere near downtown" verbatim
(correct — no hallucinated fake address) but doesn't reliably flag it as
missing on its own. _missing_booking_fields() is the independent check that
catches that. Covered here so the fix stays fixed.
"""

from routes.voice import _missing_booking_fields


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
