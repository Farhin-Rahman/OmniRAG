import logging
from uuid import UUID, uuid4
import fitz  # PyMuPDF
from config.settings import settings
from services.db.sqlite_service import SessionLocal
from repositories.document_repository import DocumentRepository
from services.embedding_service import embedding_service
from services.db.qdrant_service import get_qdrant_service
from services.storage.file_storage import get_file_storage
from PIL import Image
import io

logger = logging.getLogger(__name__)


async def process_document_background(doc_id: str):
    """
    Background task to process a document:
    1. Read PDF with PyMuPDF
    2. Chunk text
    3. Generate embeddings
    4. Upsert to Qdrant
    5. Update document status
    """
    logger.info(f"Starting background ingestion for doc_id: {doc_id}")
    db = SessionLocal()
    qdrant = get_qdrant_service()

    try:
        # Get document from DB
        document = DocumentRepository.get(db, UUID(doc_id))
        if not document:
            logger.error(f"Document {doc_id} not found in DB")
            return

        # Update status
        document.status = "processing"
        db.commit()

        # Load file
        storage = get_file_storage()
        file_path = storage._get_file_path(UUID(doc_id), document.mime)

        # Parse and chunk using PyMuPDF (with OCR fallback)
        chunks = []
        with fitz.open(file_path) as doc:
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text("text").strip()

                # OCR Fallback if no text extracted (scanned document)
                if not text:
                    logger.info(
                        f"Page {page_num + 1} has no text. Attempting OCR fallback."
                    )
                    try:
                        import easyocr
                        import numpy as np

                        pix = page.get_pixmap(
                            matrix=fitz.Matrix(2, 2)
                        )  # 2x zoom for better OCR
                        img_data = pix.tobytes("png")
                        img = Image.open(io.BytesIO(img_data))
                        img_array = np.array(img)

                        # Use EasyOCR to extract text
                        reader = easyocr.Reader(["ar", "en"], gpu=False, verbose=False)
                        results = reader.readtext(img_array, detail=0, paragraph=True)
                        text = " ".join(results).strip()

                        if text:
                            logger.info(
                                f"OCR successfully extracted {len(text.split())} words from page {page_num + 1} using EasyOCR"
                            )
                        else:
                            logger.info(f"OCR found no text on page {page_num + 1}")
                    except Exception as ocr_e:
                        logger.warning(f"OCR failed on page {page_num + 1}: {ocr_e}")

                if not text:
                    continue

                # Simple chunking by paragraphs or hard limit (e.g. 500 chars)
                words = text.split()
                chunk_size = 200
                for i in range(0, len(words), chunk_size):
                    chunk_text = " ".join(words[i : i + chunk_size])

                    chunks.append(
                        {
                            "chunk_id": str(uuid4()),
                            "doc_id": doc_id,
                            "doc_name": document.doc_name,
                            "page": page_num + 1,
                            "text": chunk_text,
                        }
                    )

        logger.info(f"Extracted {len(chunks)} chunks from {document.doc_name}")

        if chunks:
            # Generate embeddings and push to Qdrant in batches
            batch_size = 50
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]

                # We need to await generate_embedding for multiple texts, but embedding_service.generate_embedding currently handles a single string for query mode or a list?
                # Let's check what generate_embedding expects. Usually it's a list for "document" mode.
                # Assuming `generate_embedding` can handle single strings in a loop or lists. Let's do a loop for safety if not supported.
                for chunk in batch:
                    vector = await embedding_service.generate_embedding(
                        chunk["text"], mode="document"
                    )

                    point = {
                        "id": chunk["chunk_id"],
                        "vector": vector,
                        "payload": {
                            "chunk_id": chunk["chunk_id"],
                            "doc_id": chunk["doc_id"],
                            "doc_name": chunk["doc_name"],
                            "page": chunk["page"],
                            "text": chunk["text"],
                            "tenant_id": "default",
                            "embedding_id": settings.embedding_model,
                            "doc_type": document.doc_type,
                            "status": "ready",
                        },
                    }

                    qdrant.client.upsert(
                        collection_name=settings.qdrant_chunk_collection, points=[point]
                    )

        # A document with no extractable text (e.g. a scanned PDF where OCR
        # also failed) isn't queryable — it must not be marked "ready", or
        # it silently looks searchable while returning nothing.
        if not chunks:
            document.status = "error"
            db.commit()
            logger.warning(f"No text extracted from doc_id {doc_id}; marked as error")
            return

        document.status = "ready"
        db.commit()
        logger.info(f"Successfully ingested doc_id: {doc_id}")

    except Exception as e:
        logger.error(f"Failed to process document {doc_id}: {e}", exc_info=True)
        try:
            document = DocumentRepository.get(db, UUID(doc_id))
            if document:
                document.status = "error"
                db.commit()
        except Exception as rollback_e:
            logger.error(f"Failed to set error status for {doc_id}: {rollback_e}")
    finally:
        db.close()
