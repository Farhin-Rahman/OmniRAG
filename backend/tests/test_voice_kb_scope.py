"""The voice agent can be restricted to one document. The vector index is shared
by every demo and holds stale documents (an unrelated research paper, an older
FAQ), which a caller's off-topic question could pull into an answer."""

import asyncio

import routes.voice as voice_module


class _FakeQdrant:
    def __init__(self):
        self.calls: list[dict] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return [{"text": "Apex serves Calgary."}]


def _retrieve(monkeypatch, doc_name: str) -> dict:
    fake = _FakeQdrant()

    async def fake_embedding(text, mode=None):
        return [0.0]

    monkeypatch.setattr(voice_module, "get_qdrant_service", lambda: fake)
    monkeypatch.setattr(
        voice_module.embedding_service, "generate_embedding", fake_embedding
    )
    monkeypatch.setattr(voice_module.settings, "voice_kb_doc_name", doc_name)
    assert asyncio.run(voice_module._retrieve_context("areas?")) == [
        "Apex serves Calgary."
    ]
    return fake.calls[0]


class TestVoiceKnowledgeBaseScope:
    def test_unset_searches_everything_as_before(self, monkeypatch):
        assert _retrieve(monkeypatch, "")["acl_filter"] is None

    def test_set_restricts_the_search_to_that_document(self, monkeypatch):
        call = _retrieve(monkeypatch, "apex_hvac_faq.pdf")
        assert call["acl_filter"] == {
            "must": [{"key": "doc_name", "match": {"value": "apex_hvac_faq.pdf"}}]
        }
