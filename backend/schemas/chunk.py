from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from uuid import UUID


class Span(BaseModel):
    start: int
    end: int


class Layout(BaseModel):
    bbox: List[float] = Field(..., description="Bounding box as [x0, y0, x1, y1]")
    block_type: Literal["paragraph", "table", "figure", "caption"]


class ChunkMetadata(BaseModel):
    language: Optional[str] = "en"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    table_id: Optional[str] = None
    chunk_type: Optional[str] = "text"  # "text" or "table"
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_path: Optional[List[str]] = None


class DocumentChunk(BaseModel):
    chunk_id: UUID
    doc_id: UUID
    page: int
    section: Optional[str] = None
    span: Span
    text: str
    vector_id: Optional[str] = Field(
        None, description="ID of the vector in Qdrant or other vector DB"
    )
    embedding_id: Optional[str] = Field(
        None, description="Model identifier used for embedding"
    )
    layout: Optional[Layout] = None
    overlap: Optional[float] = Field(default=0.0, ge=0.0, le=1.0)
    checksum: Optional[str] = Field(None, description="SHA1 checksum of text content")
    chunk_metadata: Optional[ChunkMetadata] = None
