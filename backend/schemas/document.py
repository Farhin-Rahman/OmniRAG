import uuid
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from enum import Enum


class DocumentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class DocumentBase(BaseModel):
    doc_name: str = Field(..., description="Name of the document")
    sha256: str = Field(..., description="SHA256 hash of the document")
    mime: str = Field(..., description="MIME type of the document")
    pages: int = Field(..., description="Number of pages in the document")
    source_uri: str = Field(..., description="Source URI of the document")
    ingest_run_id: uuid.UUID = Field(..., description="Identifier for the ingest run")
    doc_type: str = Field(..., description="Type of the document")
    tenant_id: uuid.UUID = Field(..., description="Identifier for the tenant")
    embedding_id: str = Field(..., description="Identifier for the embedding model")


class DocumentCreate(DocumentBase):
    status: DocumentStatus = Field(..., description="Initial status of the document")


class DocumentUpdate(BaseModel):
    doc_name: str | None = None
    status: DocumentStatus | None = None
    version: int | None = None


class DocumentResponse(DocumentBase):
    doc_id: uuid.UUID = Field(..., description="Unique identifier for the document")
    status: DocumentStatus = Field(..., description="Current status of the document")
    version: int = Field(..., description="Version of the document")
    created_at: datetime = Field(
        ..., description="Timestamp when the document was created"
    )

    model_config = ConfigDict(from_attributes=True)
