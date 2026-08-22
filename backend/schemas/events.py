import uuid
from pydantic import BaseModel
from typing import List


class IngestedDocumentEvent(BaseModel):
    doc_id: uuid.UUID
    sha256: str
    pages: int
    tenant_id: uuid.UUID
    ingest_run_id: uuid.UUID


class ChunksCreatedEvent(BaseModel):
    doc_id: uuid.UUID
    ingest_run_id: uuid.UUID
    chunk_ids: List[uuid.UUID]
    embedding_id: str
    count: int


class VectorsUpsertedEvent(BaseModel):
    embedding_id: str
    doc_id: uuid.UUID
    ingest_run_id: uuid.UUID
    chunks_indexed: int
