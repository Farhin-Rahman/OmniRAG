"""
Structure-aware document chunking service.

This module provides intelligent chunking that respects document structure,
using ParsedBlocks from the Docling parser to create semantic chunks.
"""

import hashlib
import logging
import re
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from config.settings import settings
from repositories.chunk_repository import ChunkRepository
from repositories.document_repository import DocumentRepository
from schemas.chunk import ChunkMetadata, Layout
from services.parsing import ParsedBlock

logger = logging.getLogger(__name__)

# Chunking Constants (all sizes are in estimated tokens, not characters)
DEFAULT_TARGET_CHUNK_SIZE = 800  # ~600 words / ~3000 chars
DEFAULT_OVERLAP_SIZE = 150  # ~112 words / ~560 chars
DEFAULT_MAX_CHUNK_SIZE = 1200  # ~900 words / ~4500 chars
SMALL_BLOCK_THRESHOLD = 100  # tokens - blocks smaller than this get merged
WORDS_PER_TOKEN_RATIO = 0.75  # 1 token ≈ 0.75 words (for Arabic/English mix)
TABLE_LABEL_TOKEN_THRESHOLD = 25  # small label attached to a table


class ChunkingConfig:
    """Configuration for chunking behavior."""

    def __init__(
        self,
        target_size: int = DEFAULT_TARGET_CHUNK_SIZE,
        overlap_size: int = DEFAULT_OVERLAP_SIZE,
        max_size: int = DEFAULT_MAX_CHUNK_SIZE,
    ) -> None:
        self.target_size = target_size
        self.overlap_size = overlap_size
        self.max_size = max_size

        # Validate configuration
        if self.target_size > self.max_size:
            raise ValueError("Target chunk size cannot exceed max chunk size")
        if self.overlap_size >= self.target_size:
            raise ValueError("Overlap size must be less than target size")


def create_chunks_from_blocks(
    blocks: List[ParsedBlock],
    doc_id: UUID,
    tenant_id: UUID,
    config: Optional[ChunkingConfig] = None,
) -> List[Dict[str, any]]:
    """
    Create chunks from ParsedBlocks with structure awareness.

    Args:
        blocks: List of ParsedBlock objects from document parser
        doc_id: Document UUID
        tenant_id: Tenant UUID
        config: Optional chunking configuration

    Returns:
        List of chunk dictionaries ready for database insertion
    """
    if not blocks:
        logger.warning("No blocks provided for document %s", doc_id)
        return []

    if config is None:
        config = ChunkingConfig()

    # Group blocks by section for semantic chunking
    sections = _group_blocks_by_section(blocks)

    chunk_records: List[Dict[str, any]] = []
    for section_path, section_blocks in sections.items():
        logger.debug(
            "Chunking section '%s' with %d blocks for document %s",
            section_path,
            len(section_blocks),
            doc_id,
        )
        section_chunks = _chunk_section(section_blocks, doc_id, config)
        chunk_records.extend(section_chunks)

    logger.info(
        "Created %d chunks from %d blocks for document %s",
        len(chunk_records),
        len(blocks),
        doc_id,
    )
    return chunk_records


def _group_blocks_by_section(blocks: List[ParsedBlock]) -> Dict[str, List[ParsedBlock]]:
    """Group blocks by their section path."""
    sections: Dict[str, List[ParsedBlock]] = defaultdict(list)

    for block in blocks:
        # Create section key from path
        section_key = " > ".join(block.section_path) if block.section_path else "root"
        sections[section_key].append(block)

    return dict(sections)  # Convert defaultdict to regular dict


def _chunk_section(
    blocks: List[ParsedBlock],
    doc_id: UUID,
    config: ChunkingConfig,
) -> List[Dict[str, any]]:
    """
    Chunk blocks within a section intelligently.

    Rules:
    - Text blocks are grouped to reach target size
    - Tables are kept as individual chunks
    - Maintain context with overlap between chunks
    - Small heading/label blocks adjacent to tables become labels only,
      not standalone chunks.
    """
    chunks: List[Dict[str, any]] = []
    current_text_blocks: List[ParsedBlock] = []
    current_tokens = 0

    for i, block in enumerate(blocks):
        if block.type == "table":
            # If the last text block is a tiny label (e.g. "Tax Summary"),
            # keep it only as a label for the table, not as its own chunk.
            label_candidate: Optional[ParsedBlock] = None
            if current_text_blocks:
                last_block = current_text_blocks[-1]
                last_tokens = _estimate_tokens(last_block.get_content())
                if last_tokens <= TABLE_LABEL_TOKEN_THRESHOLD:
                    label_candidate = last_block
                    current_text_blocks = current_text_blocks[:-1]
                    current_tokens = sum(
                        _estimate_tokens(b.get_content()) for b in current_text_blocks
                    )

            # Flush any remaining text blocks
            if current_text_blocks:
                chunk = _create_text_chunk(current_text_blocks, doc_id)
                if chunk:
                    chunks.append(chunk)
                current_text_blocks = []
                current_tokens = 0

            # For labels, prefer the explicit neighbour search, but pass
            # the popped label_candidate as a fallback.
            label_before, label_after = _find_adjacent_labels(blocks, i)

            if not label_before and label_candidate is not None:
                label_before = label_candidate.get_content().strip()

            table_chunk = _create_table_chunk(
                block,
                doc_id,
                label_before,
                label_after,
            )
            if table_chunk:
                chunks.append(table_chunk)

        elif block.type == "text":
            block_tokens = _estimate_tokens(block.get_content())

            # Check if adding this block would exceed max size
            if current_tokens > 0 and current_tokens + block_tokens > config.max_size:
                chunk = _create_text_chunk(current_text_blocks, doc_id)
                if chunk:
                    chunks.append(chunk)

                overlap_blocks = _get_overlap_blocks(
                    current_text_blocks,
                    config.overlap_size,
                )
                current_text_blocks = overlap_blocks + [block]
                current_tokens = sum(
                    _estimate_tokens(b.get_content()) for b in current_text_blocks
                )
            else:
                current_text_blocks.append(block)
                current_tokens += block_tokens

            # Flush based on target size, but allow small next-block merge
            if current_tokens >= config.target_size:
                if _should_include_next_block(blocks, i, SMALL_BLOCK_THRESHOLD):
                    continue

                chunk = _create_text_chunk(current_text_blocks, doc_id)
                if chunk:
                    chunks.append(chunk)

                overlap_blocks = _get_overlap_blocks(
                    current_text_blocks,
                    config.overlap_size,
                )
                current_text_blocks = overlap_blocks
                current_tokens = sum(
                    _estimate_tokens(b.get_content()) for b in overlap_blocks
                )

    if current_text_blocks:
        chunk = _create_text_chunk(current_text_blocks, doc_id)
        if chunk:
            chunks.append(chunk)

    return chunks


def _should_include_next_block(
    blocks: List[ParsedBlock],
    current_idx: int,
    threshold: int,
) -> bool:
    """Check if the next block should be included in current chunk."""
    if current_idx + 1 >= len(blocks):
        return False

    next_block = blocks[current_idx + 1]
    if next_block.type != "text":
        return False

    next_tokens = _estimate_tokens(next_block.get_content())
    return next_tokens < threshold


def _create_text_chunk(
    blocks: List[ParsedBlock],
    doc_id: UUID,
) -> Optional[Dict[str, any]]:
    """Create a text chunk from multiple blocks."""
    if not blocks:
        return None

    # Combine text from all blocks
    text_parts = [block.get_content() for block in blocks]
    chunk_text = "\n\n".join(text_parts)

    if not chunk_text.strip():
        return None

    # Extract metadata
    page_start = min(block.page_start for block in blocks)
    page_end = max(block.page_end for block in blocks)
    section_path = blocks[0].section_path if blocks else []
    section_title = " > ".join(section_path) if section_path else None

    # Determine primary language
    languages = [block.language for block in blocks]
    primary_language = max(set(languages), key=languages.count) if languages else "en"

    # Calculate average confidence
    confidences = [block.confidence for block in blocks if block.confidence > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 1.0

    chunk_id = uuid4()

    kv_meta = _extract_kv_metadata(chunk_text)
    chunk_type = "kv" if kv_meta else "text"

    chunk_metadata = ChunkMetadata(
        language=primary_language,
        confidence=float(avg_confidence),
        table_id=None,
        chunk_type=chunk_type,
        page_start=page_start,
        page_end=page_end,
        section_path=section_path,
    ).model_dump()

    if kv_meta:
        chunk_metadata.update({"kv": kv_meta})

    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "page": page_start,  # Primary page
        "section": section_title,
        "span": {"start": 0, "end": len(chunk_text)},
        "text": chunk_text,
        "vector_id": None,
        "embedding_id": settings.embedding_model,
        "layout": None,  # Text chunks don't have single layout
        "overlap": 0.0,
        "checksum": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        "chunk_metadata": chunk_metadata,
    }


def _create_table_chunk(
    block: ParsedBlock,
    doc_id: UUID,
    label_before: Optional[str],
    label_after: Optional[str],
) -> Optional[Dict[str, any]]:
    """Create a chunk for a table block."""
    if block.type != "table" or not block.table_markdown:
        return None

    chunk_text_parts: List[str] = []
    if label_before:
        chunk_text_parts.append(label_before)
    chunk_text_parts.append(block.table_markdown)
    if label_after:
        chunk_text_parts.append(label_after)

    chunk_text = "\n\n".join(chunk_text_parts)

    chunk_id = uuid4()

    table_metadata = {
        "chunk_type": "table",
        "table": _extract_table_grid(block),
        "label_before": label_before,
        "label_after": label_after,
    }

    # Derive a reasonable section string: prefer explicit section_title,
    # otherwise derive from section_path (same as text chunks).
    if block.section_title:
        section_title = block.section_title
    elif block.section_path:
        section_title = " > ".join(block.section_path)
    else:
        section_title = None

    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "page": block.page_start,
        "section": section_title,
        "span": {"start": 0, "end": len(chunk_text)},
        "text": chunk_text,
        "vector_id": None,
        "embedding_id": settings.embedding_model,
        "layout": (
            Layout(bbox=block.bbox, block_type="table").model_dump()
            if block.bbox
            else None
        ),
        "overlap": 0.0,
        "checksum": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        "chunk_metadata": {
            **ChunkMetadata(
                language="en",  # Tables typically in English; adjust if needed later
                confidence=float(block.confidence),
                table_id=str(chunk_id),  # Self-reference for table tracking
                chunk_type="table",
                page_start=block.page_start,
                page_end=block.page_end,
                section_path=block.section_path,
            ).model_dump(),
            **table_metadata,
        },
    }


def _get_overlap_blocks(
    blocks: List[ParsedBlock],
    overlap_tokens: int,
) -> List[ParsedBlock]:
    """Get blocks from the end that fit within overlap token budget."""
    if not blocks or overlap_tokens <= 0:
        return []

    overlap_blocks: List[ParsedBlock] = []
    token_count = 0

    # Work backwards to get trailing context
    for block in reversed(blocks):
        block_tokens = _estimate_tokens(block.get_content())
        if token_count + block_tokens <= overlap_tokens:
            overlap_blocks.insert(0, block)
            token_count += block_tokens
        else:
            # Can't fit entire block, stop here
            break

    return overlap_blocks


def _find_adjacent_labels(
    blocks: List[ParsedBlock],
    idx: int,
) -> Tuple[Optional[str], Optional[str]]:
    """
    For a table at position idx, find small neighbouring text blocks to use as labels.
    """
    before: Optional[str] = None
    after: Optional[str] = None

    # Look backwards
    if idx - 1 >= 0:
        prev_block = blocks[idx - 1]
        if prev_block.type == "text":
            tokens = _estimate_tokens(prev_block.get_content())
            if tokens <= TABLE_LABEL_TOKEN_THRESHOLD:
                before = prev_block.get_content().strip()

    # Look forwards
    if idx + 1 < len(blocks):
        next_block = blocks[idx + 1]
        if next_block.type == "text":
            tokens = _estimate_tokens(next_block.get_content())
            if tokens <= TABLE_LABEL_TOKEN_THRESHOLD:
                after = next_block.get_content().strip()

    return before, after


def _extract_kv_metadata(text: str) -> Optional[Dict[str, str]]:
    """
    Extract simple key-value patterns from short lines in the chunk.

    Supports generic separators like ':', '-', '—'.

    We intentionally work line-by-line and only consider short lines,
    so large invoice / contract chunks can still yield KV metadata
    for things like:

        Quote Date : 01 Oct 2025
        Expiry Date : 10 Oct 2025

    Also handles multi-line patterns where key and value are on separate lines:
        Quote Date :
        01 Oct 2025
    """
    if not text:
        return None

    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and "|" not in ln  # avoid table markdown lines
    ]

    # Pattern 1: Key and value on same line
    same_line_pattern = r"^\s*(.+?)\s*[:\-—]\s*(.+?)\s*$"

    for line in lines:
        # Ignore extremely long lines to reduce false positives
        if len(line) > 200:
            continue
        match = re.match(same_line_pattern, line)
        if match:
            key = match.group(1).strip()
            value = match.group(2).strip()
            if key and value:
                return {
                    "kv_key": key,
                    "kv_value": value,
                    "line_text": line.strip(),
                }

    # Pattern 2: Key on one line ending with separator, value on next line
    key_only_pattern = r"^\s*(.+?)\s*[:\-—]\s*$"

    for i, line in enumerate(lines):
        if len(line) > 200:
            continue
        match = re.match(key_only_pattern, line)
        if match and i + 1 < len(lines):
            key = match.group(1).strip()
            next_line = lines[i + 1]
            # Value should be short and not contain separators (to avoid false matches)
            if len(next_line) <= 50 and not re.search(r"[:\-—]", next_line):
                value = next_line.strip()
                if key and value:
                    return {
                        "kv_key": key,
                        "kv_value": value,
                        "line_text": f"{line}\n{next_line}",
                    }

    return None


def _extract_table_grid(block: ParsedBlock) -> Optional[Dict[str, any]]:
    """
    Convert a Docling table block into a structured grid if possible.
    Falls back to None if structure is unavailable.
    """
    # Use table_data directly from the block instead of checking TableItem type

    # Prefer the explicit table_data we stored from Docling
    table_data = getattr(block, "table_data", None)
    rows = getattr(table_data, "rows", None) if table_data else None

    if rows:
        headers = rows[0] if rows else []
        body = rows[1:] if rows and len(rows) > 1 else []
        return {
            "headers": [str(h) for h in headers],
            "rows": [[str(c) for c in row] for row in body],
        }

    # Fallback: try to parse markdown into rows (best-effort)
    if block.table_markdown:
        lines = [
            ln.strip("| ").strip()
            for ln in block.table_markdown.splitlines()
            if ln.strip()
        ]
        if len(lines) >= 2:
            headers = [cell.strip() for cell in lines[0].split("|")]
            body: List[List[str]] = []
            # Skip separator line (lines[1]); start from lines[2:]
            for ln in lines[2:]:
                body.append([cell.strip() for cell in ln.split("|")])
            return {"headers": headers, "rows": body}

    return None


def _estimate_tokens(text: str) -> int:
    """
    Estimate token count for text.

    Uses a simple heuristic based on word count.
    For more accurate estimates, consider using a tokenizer.
    """
    if not text:
        return 0

    # Count words using regex (handles punctuation better)
    words = re.findall(r"\b\w+\b", text)

    # Estimate tokens based on word count
    return max(1, int(len(words) / WORDS_PER_TOKEN_RATIO))


def parse_and_chunk(
    db: Session,
    doc_id: UUID,
    mime_type: str,
    tenant_id: UUID,
) -> List[UUID]:
    """
    Parse document using Docling and create structure-aware chunks.

    Args:
        db: Database session
        doc_id: Document UUID
        mime_type: MIME type of document
        tenant_id: Tenant UUID

    Returns:
        List of created chunk UUIDs

    Raises:
        FileNotFoundError: If document file not found
        RuntimeError: If parsing or chunking fails
    """
    from pathlib import Path

    from services.parsing import parse_document
    from services.storage.file_storage import get_file_storage

    # Get file path
    file_storage = get_file_storage()
    if not file_storage.file_exists(doc_id, mime_type):
        raise FileNotFoundError(f"Document file not found for doc_id: {doc_id}")

    file_path = Path(file_storage._get_file_path(doc_id, mime_type))

    logger.info("Parsing document %s with Docling parser", doc_id)

    try:
        # Parse document into blocks
        blocks = parse_document(file_path, doc_id, tenant_id)

        if not blocks:
            logger.warning("No blocks extracted from document %s", doc_id)
            return []

        logger.info("Extracted %d blocks from document %s", len(blocks), doc_id)

        # Load chunking configuration (sizes are in tokens, not characters)
        # Settings can override defaults if needed
        config = ChunkingConfig(
            target_size=getattr(
                settings,
                "chunk_target_tokens",
                DEFAULT_TARGET_CHUNK_SIZE,
            ),
            overlap_size=getattr(
                settings,
                "chunk_overlap_tokens",
                DEFAULT_OVERLAP_SIZE,
            ),
            max_size=getattr(
                settings,
                "chunk_max_tokens",
                DEFAULT_MAX_CHUNK_SIZE,
            ),
        )

        # Create chunks from blocks
        chunk_records = create_chunks_from_blocks(blocks, doc_id, tenant_id, config)

        if not chunk_records:
            logger.warning("No chunks created from blocks for document %s", doc_id)
            return []

        # Save chunks to database
        created_chunks = ChunkRepository.create_bulk(db, chunk_records)

        # Log chunk details
        for i, chunk in enumerate(created_chunks[:3]):  # First 3 chunks only
            logger.info(
                "Created chunk %d: type=%s, page=%s, text_preview='%s...'",
                i + 1,
                chunk.chunk_metadata.get("chunk_type", "unknown"),
                chunk.page,
                chunk.text[:100].replace("\n", " "),
            )
        if len(created_chunks) > 3:
            logger.info(
                "...and %d more chunks created",
                len(created_chunks) - 3,
            )

        # Update document pages count
        max_page = max(
            (record["chunk_metadata"].get("page_end", 1) for record in chunk_records),
            default=1,
        )
        document = DocumentRepository.get_by_id(db, doc_id, tenant_id)
        if document:
            document.pages = max_page

        db.commit()

        logger.info("Created %d chunks for document %s", len(created_chunks), doc_id)
        return [chunk.chunk_id for chunk in created_chunks]

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to parse and chunk document %s: %s", doc_id, exc)
        db.rollback()
        raise RuntimeError(f"Document processing failed: {exc}") from exc


def embed_and_upsert_chunks(
    db,
    doc_id: UUID,
    tenant_id: UUID,
    chunk_ids: List[UUID],
) -> None:
    """
    Generate embeddings and upsert chunks to vector database.

    Args:
        db: Database session
        doc_id: Document UUID
        tenant_id: Tenant UUID
        chunk_ids: List of chunk UUIDs to process
    """
    from repositories.chunk_repository import ChunkRepository
    from repositories.document_repository import DocumentRepository
    from services.embedding_service import embedding_service
    from services.db.qdrant_service import get_qdrant_service

    if not chunk_ids:
        logger.warning("No chunks to embed for document %s", doc_id)
        return

    try:
        # Get document to fetch doc_type
        document = DocumentRepository.get_by_id(db, doc_id, tenant_id)
        if not document:
            logger.error("Document %s not found in database", doc_id)
            return

        # Fetch chunks efficiently by their IDs
        chunk_uuids = [UUID(cid) if isinstance(cid, str) else cid for cid in chunk_ids]
        chunks = ChunkRepository.get_by_chunk_ids(db, chunk_uuids)

        if not chunks:
            logger.error(
                "No chunks found in database for document %s",
                doc_id,
            )
            return

        logger.info("Generating embeddings for %d chunks", len(chunks))

        # Extract texts for embedding
        texts = [chunk.text for chunk in chunks]
        for i, chunk in enumerate(chunks[:2]):  # First 2 chunks
            logger.info(
                "Embedding chunk %d: text_len=%d, preview='%s...'",
                i + 1,
                len(chunk.text),
                chunk.text[:80].replace("\n", " "),
            )
        if len(chunks) > 2:
            logger.info("...embedding %d more chunks", len(chunks) - 2)

        # Process in batches for large documents to avoid timeout/memory issues
        BATCH_SIZE = 100  # Increased since ML service can handle it

        def _embed_batch(batch_texts: List[str]) -> List[List[float]]:
            backoff = [0.5, 1.0, 2.0]
            for attempt, delay in enumerate([0.0] + backoff):
                if delay:
                    time.sleep(delay)
                try:
                    return embedding_service.generate_embedding_sync(batch_texts)
                except Exception as exc_inner:  # noqa: BLE001
                    logger.warning(
                        "Embedding batch failed (attempt %d/%d, batch_size=%d): %s",
                        attempt + 1,
                        len(backoff) + 1,
                        len(batch_texts),
                        exc_inner,
                    )
                    if attempt == len(backoff):
                        raise
            return []

        if len(texts) <= BATCH_SIZE:
            embeddings = _embed_batch(texts)
        else:
            embeddings: List[List[float]] = []
            batch_size = BATCH_SIZE
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                logger.info(
                    "Processing embedding batch %d/%d",
                    (i // batch_size) + 1,
                    (len(texts) + batch_size - 1) // batch_size,
                )
                try:
                    batch_embeddings = _embed_batch(batch)
                except Exception:  # noqa: BLE001
                    # Retry with smaller batch to recover from transient issues
                    if batch_size > 20:
                        batch_size = max(20, batch_size // 2)
                        logger.info(
                            "Reducing batch size to %d and retrying",
                            batch_size,
                        )
                        batch_embeddings = _embed_batch(batch[:batch_size])
                        batch_embeddings += _embed_batch(batch[batch_size:])
                    else:
                        raise
                embeddings.extend(batch_embeddings)

        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding count mismatch: chunks={len(chunks)} embeddings={len(embeddings)}"
            )

        logger.info("Generated %d embeddings", len(embeddings))

        # Get ACLs for Qdrant payload
        from services.acl_service import get_doc_acl_for_qdrant

        acl_users, acl_groups = get_doc_acl_for_qdrant(doc_id, db)

        # Prepare data for Qdrant
        chunks_data = []
        for chunk, embedding in zip(chunks, embeddings):
            meta = chunk.chunk_metadata or {}
            chunks_data.append(
                {
                    "chunk_id": str(chunk.chunk_id),
                    "vector": embedding,
                    "payload": {
                        "chunk_id": str(chunk.chunk_id),
                        "doc_id": str(chunk.doc_id),
                        "tenant_id": str(tenant_id),
                        # ACL fields for filtering
                        "acl_users": acl_users,
                        "acl_groups": acl_groups,
                        "text": chunk.text,
                        "page": chunk.page,
                        "section": chunk.section,
                        "embedding_id": chunk.embedding_id,
                        "doc_type": document.doc_type,
                        "doc_name": document.doc_name,
                        # Document-level metadata for ACL and filtering
                        "source_uri": document.source_uri,
                        "mime": document.mime,
                        "pages": document.pages,
                        "sha256": document.sha256,
                        "created_at": document.created_at.isoformat()
                        if document.created_at
                        else None,
                        "status": document.status,
                        "version": document.version,
                        "chunk_type": meta.get("chunk_type"),
                        "kv_key": meta.get("kv", {}).get("kv_key")
                        if isinstance(meta.get("kv"), dict)
                        else None,
                        "kv_value": meta.get("kv", {}).get("kv_value")
                        if isinstance(meta.get("kv"), dict)
                        else None,
                    },
                },
            )

        # Upsert to Qdrant
        qdrant_service = get_qdrant_service()
        upserted = qdrant_service.upsert_chunks(chunks_data)

        logger.info(
            "Upserted %d chunks to Qdrant for document %s",
            upserted,
            doc_id,
        )

        # Update chunks with vector IDs after successful Qdrant upsert
        for chunk in chunks:
            ChunkRepository.update_vector_id(
                db,
                chunk.chunk_id,
                str(chunk.chunk_id),  # Using chunk_id as vector_id
            )

        db.commit()

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to embed and upsert chunks for document %s: %s",
            doc_id,
            exc,
            exc_info=True,
        )
        db.rollback()
        raise
