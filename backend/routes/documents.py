from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from datetime import datetime

from services.db.sqlite_service import get_db
from sqlalchemy import text

router = APIRouter(tags=["Documents"])


class DocumentResponse(BaseModel):
    doc_id: str
    doc_name: str
    status: str
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: List[DocumentResponse]


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(limit: int = 20):
    db = next(get_db())
    try:
        # Fetch directly from sqlite for simplicity
        docs = db.execute(
            text(
                "SELECT doc_id, doc_name, status, created_at FROM documents ORDER BY created_at DESC LIMIT :limit"
            ),
            {"limit": limit},
        ).fetchall()

        result = []
        for d in docs:
            result.append(
                DocumentResponse(
                    doc_id=str(d.doc_id),
                    doc_name=d.doc_name,
                    status=d.status,
                    created_at=d.created_at,
                )
            )

        return DocumentListResponse(documents=result)
    finally:
        db.close()
