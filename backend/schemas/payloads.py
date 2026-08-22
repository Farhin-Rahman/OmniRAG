from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ScoreMeta(BaseModel):
    bm25: Optional[float] = Field(None, description="BM25 score used for ranking")
    recency: Optional[float] = Field(None, description="Recency score or decay weight")


class QdrantChunkPayload(BaseModel):
    chunk_id: UUID
    doc_id: UUID
    page: int
    section: Optional[str] = None
    embedding_id: str
    doc_type: str
    tenant_id: UUID
    text: str
    relations: list = Field(
        default_factory=list, description="List of relation metadata"
    )
    entities: Optional[List[str]] = Field(
        None, description="Entity IDs for filter boosts"
    )
    rel_types: Optional[List[str]] = Field(None, description="Relation type summaries")
    score_meta: Optional[ScoreMeta] = None


class QdrantDocPayload(BaseModel):
    doc_id: UUID
    embedding_id: str
    tenant_id: UUID
    doc_type: str
    doc_name: str = Field(..., description="Document filename")
    source_uri: str = Field(..., description="Original source URI")
    mime: str = Field(..., description="MIME type of the document")
    pages: int = Field(0, description="Number of pages in document")
    created_at: str = Field(..., description="ISO timestamp of document creation")
    entity_summary: Optional[List[str]] = Field(
        None, description="Entity summaries for coarse routing"
    )
