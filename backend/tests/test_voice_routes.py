"""HTTP-seam tests for the voice agent routes: config guards, the booking
list, and the outbound-call route's error paths. Anything that would
require a real Retell call, a live LLM, or Qdrant is out of scope here —
those are exercised by hand against the deployed stack, not mocked.
"""

import db.bookings as bookings_module
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routes.voice as voice_module

app = FastAPI()
app.include_router(voice_module.router)
client = TestClient(app)


class TestBookingsEndpoint:
    def _setup(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        monkeypatch.setattr(bookings_module, "DB_PATH", db_path)
        bookings_module.init_bookings_db()

    def test_empty_when_nothing_booked(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        resp = client.get("/voice/bookings")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_a_recorded_booking(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        bookings_module.record_booking(
            service="furnace repair",
            call_id="call-1",
            address="142 Maple Crescent, Calgary, AB",
            phone="4035551234",
            customer_name="Jane Doe",
        )
        resp = client.get("/voice/bookings")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["service"] == "furnace repair"
        assert data[0]["address"] == "142 Maple Crescent, Calgary, AB"
        assert data[0]["status"] == "confirmed"


class TestWebCallConfigGuard:
    def test_503_when_retell_not_configured(self, monkeypatch):
        monkeypatch.setattr(voice_module.settings, "retell_api_key", "")
        monkeypatch.setattr(voice_module.settings, "retell_agent_id", "")
        resp = client.post("/voice/web-call")
        assert resp.status_code == 503


class TestOutboundFollowUpConfigGuard:
    def test_503_when_retell_not_configured(self, monkeypatch):
        monkeypatch.setattr(voice_module.settings, "retell_api_key", "")
        monkeypatch.setattr(voice_module.settings, "retell_agent_id", "")
        monkeypatch.setattr(voice_module.settings, "retell_from_number", "")
        resp = client.post(
            "/voice/outbound-follow-up",
            json={"booking_id": 1, "to_number": "+15875551234"},
        )
        assert resp.status_code == 503

    def test_503_when_from_number_not_configured(self, monkeypatch):
        monkeypatch.setattr(voice_module.settings, "retell_api_key", "key")
        monkeypatch.setattr(voice_module.settings, "retell_agent_id", "agent")
        monkeypatch.setattr(voice_module.settings, "retell_from_number", "")
        resp = client.post(
            "/voice/outbound-follow-up",
            json={"booking_id": 1, "to_number": "+15875551234"},
        )
        assert resp.status_code == 503
        assert "RETELL_FROM_NUMBER" in resp.json()["detail"]

    def test_404_when_booking_does_not_exist(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test.db")
        monkeypatch.setattr(bookings_module, "DB_PATH", db_path)
        bookings_module.init_bookings_db()

        monkeypatch.setattr(voice_module.settings, "retell_api_key", "key")
        monkeypatch.setattr(voice_module.settings, "retell_agent_id", "agent")
        monkeypatch.setattr(voice_module.settings, "retell_from_number", "+15005550006")

        resp = client.post(
            "/voice/outbound-follow-up",
            json={"booking_id": 999, "to_number": "+15875551234"},
        )
        assert resp.status_code == 404
