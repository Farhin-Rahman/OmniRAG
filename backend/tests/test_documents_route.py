"""HTTP-seam test for GET /documents.

Note: routes/documents.py calls get_db() directly as a plain generator
function inside the route body, not via FastAPI's Depends() — so
app.dependency_overrides has no effect on it. Isolation here works by
monkeypatching the `get_db` name in routes.documents' own module
namespace instead, which the route resolves at call time. Without this,
the test would silently hit the real data/omnirag.db and see production
documents (confirmed the hard way while writing this).
"""

import uuid

import routes.documents as documents_module
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models.base import Base, Document

app = FastAPI()
app.include_router(documents_module.router)
client = TestClient(app)


def _fresh_isolated_db(monkeypatch):
    # StaticPool: a plain in-memory sqlite:// engine hands each new
    # connection a *separate*, empty in-memory database — the table
    # created below would be invisible to the route's own connection.
    # StaticPool keeps every checkout on the one connection so they share
    # the same in-memory database (confirmed the hard way: first attempt
    # without this hit "no such table: documents").
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def fake_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(documents_module, "get_db", fake_get_db)
    return TestSession


def _insert_document(session_factory, doc_name: str, status: str) -> str:
    db = session_factory()
    doc_id = uuid.uuid4()
    db.add(
        Document(
            doc_id=doc_id,
            doc_name=doc_name,
            source_uri=f"/tmp/{doc_name}",
            sha256=uuid.uuid4().hex,
            mime="application/pdf",
            doc_type="pdf",
            ingest_run_id=uuid.uuid4(),
            status=status,
            embedding_id="nomic-embed-text",
        )
    )
    db.commit()
    db.close()
    return str(doc_id)


class TestListDocuments:
    def test_empty_list_when_nothing_ingested(self, monkeypatch):
        _fresh_isolated_db(monkeypatch)
        resp = client.get("/documents")
        assert resp.status_code == 200
        assert resp.json() == {"documents": []}

    def test_returns_ingested_documents(self, monkeypatch):
        session_factory = _fresh_isolated_db(monkeypatch)
        doc_id = _insert_document(session_factory, "apex_hvac_faq.pdf", "ready")
        resp = client.get("/documents")
        assert resp.status_code == 200
        docs = resp.json()["documents"]
        assert any(d["doc_id"] == doc_id and d["status"] == "ready" for d in docs)

    def test_limit_is_respected(self, monkeypatch):
        session_factory = _fresh_isolated_db(monkeypatch)
        for i in range(5):
            _insert_document(session_factory, f"doc-{i}.pdf", "ready")
        resp = client.get("/documents", params={"limit": 2})
        assert resp.status_code == 200
        assert len(resp.json()["documents"]) == 2
