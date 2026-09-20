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


class TestScopeInfrastructure:
    def test_doc_name_gets_a_payload_index(self):
        """Qdrant Cloud rejects filtering on an unindexed field, so scoping by
        doc_name without this index made every voice answer fail in production
        while passing against the local Docker Qdrant."""
        from services.db.qdrant_service import QdrantService

        indexed: list[str] = []

        class _Client:
            def create_payload_index(self, collection_name, field_name, **kwargs):
                indexed.append(field_name)

        service = QdrantService.__new__(QdrantService)
        service.client = _Client()
        service._ensure_payload_indexes("chunks")
        assert "doc_name" in indexed

    def test_a_failed_search_degrades_to_no_context_instead_of_raising(
        self, monkeypatch
    ):
        class _Broken:
            def search(self, **kwargs):
                raise RuntimeError("Index required but not found for doc_name")

        async def fake_embedding(text, mode=None):
            return [0.0]

        monkeypatch.setattr(voice_module, "get_qdrant_service", lambda: _Broken())
        monkeypatch.setattr(
            voice_module.embedding_service, "generate_embedding", fake_embedding
        )
        assert asyncio.run(voice_module._retrieve_context("areas?")) == []


class TestVoiceKnowledgeBaseScope:
    def test_unset_searches_everything_as_before(self, monkeypatch):
        assert _retrieve(monkeypatch, "")["acl_filter"] is None

    def test_set_restricts_the_search_to_that_document(self, monkeypatch):
        call = _retrieve(monkeypatch, "apex_hvac_faq.pdf")
        assert call["acl_filter"] == {
            "must": [{"key": "doc_name", "match": {"value": "apex_hvac_faq.pdf"}}]
        }
