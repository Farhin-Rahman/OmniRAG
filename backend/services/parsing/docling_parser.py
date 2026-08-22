"""
Docling-based document parser with structured output.

Parses PDFs and images into structured blocks (text, tables) with section hierarchy.
Uses Docling as the primary parser and PaddleOCR as a fallback for scanned content.

Best-practice updates:
- Never hard-fail the whole ingestion just because OCR can't initialize (slow/blocked network).
  If OCR init fails, we keep any PyMuPDF text and continue gracefully.
- Fix PyMuPDF (RGB) -> PaddleOCR (BGR) conversion in OCR fallback paths.
- Best-effort OCR init is attempted once per parsing call-site (selective OCR + fallback).
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID

import numpy as np

logger = logging.getLogger(__name__)

# Language / layout constants
ARABIC_CHAR_RANGES = [("\u0600", "\u06ff"), ("\u0750", "\u077f")]
MIN_TEXT_LENGTH = 50
PAGE_ZOOM_FACTOR = 2.0
ARABIC_RATIO_THRESHOLD = 0.8
MIXED_LANG_THRESHOLD = 0.2
SCANNED_PAGE_MIN_WORDS = 0.5  # Ratio of meaningful words for scanned detection
PAGE_MIN_CHARS = 80  # Threshold to decide if a page is too sparse
PAGE_LOW_ARABIC_RATIO = 0.02  # Only trigger OCR on very low Arabic signal

# Docling conversion timeout (seconds) in the pipeline
DOCLING_CONVERSION_TIMEOUT_SEC = 300


@dataclass
class ParsedBlock:
    """Structured representation of a document block."""

    type: Literal["text", "table"]
    text: Optional[str] = None
    table_markdown: Optional[str] = None
    page_start: int = 1
    page_end: int = 1
    section_title: Optional[str] = None
    section_path: List[str] = field(default_factory=list)
    bbox: Optional[List[float]] = None  # [x0, y0, x1, y1]
    confidence: float = 1.0
    language: Literal["ar", "en", "mixed"] = "en"
    # Extra fields to keep Docling structure for downstream consumers (chunker)
    raw_element: Any | None = field(default=None, repr=False)
    table_data: Any | None = None

    def __post_init__(self) -> None:
        """Validate block data after initialization."""
        if self.type == "text" and not self.text:
            raise ValueError("Text block must have text content")
        if self.type == "table" and not self.table_markdown:
            raise ValueError("Table block must have table_markdown content")

    def get_content(self) -> str:
        """Get the main content of the block."""
        if self.type == "text":
            return self.text or ""
        if self.type == "table":
            return self.table_markdown or ""
        return ""


# Docling converter singleton (expensive models loaded once per worker)
_DOC_CONVERTER: Any | None = None


def _get_docling_converter() -> Any:
    """
    Get a singleton Docling DocumentConverter configured for PDFs.

    We intentionally:
      - Disable Docling OCR (we have our own OCR pipeline as fallback).
      - Enable table structure detection.
      - Disable picture image extraction to keep CPU/memory reasonable.

    This mirrors the configuration in the standalone diagnostic script
    that you confirmed is fast and stable.
    """
    global _DOC_CONVERTER  # noqa: PLW0603
    if _DOC_CONVERTER is not None:
        logger.info("Using cached Docling converter (PID=%s)", os.getpid())
        return _DOC_CONVERTER

    logger.info("Initializing Docling converter (PID=%s)...", os.getpid())
    start = time.time()

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        logger.error("Docling not installed. Install with: pip install docling")
        raise ImportError("Docling is required for document parsing") from exc

    pipeline_options = PdfPipelineOptions()

    # ❌ Disable Docling OCR – we rely on our own OCR fallback (PaddleOCR)
    pipeline_options.do_ocr = False

    # ✅ Enable table structure (TableFormer)
    pipeline_options.do_table_structure = True
    if hasattr(pipeline_options, "table_structure_options"):
        pipeline_options.table_structure_options.do_cell_matching = True

    # ❌ Avoid generating images / picture descriptions (keeps things lighter)
    if hasattr(pipeline_options, "generate_picture_images"):
        pipeline_options.generate_picture_images = False
    if hasattr(pipeline_options, "do_picture_description"):
        pipeline_options.do_picture_description = False

    format_options = {
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
    }

    converter = DocumentConverter(
        format_options=format_options,
        allowed_formats=[InputFormat.PDF],
    )

    logger.info(
        "Docling pipeline options: do_ocr=%s, do_table_structure=%s, do_picture_description=%s",
        getattr(pipeline_options, "do_ocr", None),
        getattr(pipeline_options, "do_table_structure", None),
        getattr(pipeline_options, "do_picture_description", None),
    )

    logger.info(
        "Docling converter initialized in %.2fs (PID=%s)",
        time.time() - start,
        os.getpid(),
    )

    _DOC_CONVERTER = converter
    return _DOC_CONVERTER


def _run_docling_conversion(converter: Any, file_path: Path) -> Any:
    """
    Thin wrapper around DocumentConverter.convert for a single source.

    Some Docling versions return an iterator/generator; we normalize by taking the first
    item if it is an iterator.
    """
    source = str(file_path)
    convert = getattr(converter, "convert", None)
    if not callable(convert):
        raise RuntimeError(
            "Docling DocumentConverter has no 'convert' method; "
            "check the installed docling version."
        )

    logger.info("Using Docling.convert(...) for %s", source)

    res = convert(source)

    try:
        from collections.abc import Iterator
    except ImportError:  # pragma: no cover
        Iterator = None  # type: ignore

    if Iterator is not None and isinstance(res, Iterator):
        try:
            first = next(res)
            logger.info("Docling conversion returned an iterator, using first result")
            return first
        except StopIteration:
            raise RuntimeError("Docling.convert returned an empty iterator") from None

    logger.info("Docling conversion returned a single ConversionResult")
    return res


def _run_docling_with_timeout(
    converter: Any,
    file_path: Path,
    timeout_sec: int = DOCLING_CONVERSION_TIMEOUT_SEC,
) -> Any:
    """
    Run Docling conversion with a hard timeout.

    This protects the Celery worker from getting stuck indefinitely. On timeout,
    the caller can fall back to OCR-based parsing.
    """

    def _convert() -> Any:
        start = time.time()
        res = _run_docling_conversion(converter, file_path)
        elapsed = time.time() - start
        logger.info("Docling conversion finished in %.2fs", elapsed)
        return res

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_convert)
        return future.result(timeout=timeout_sec)


def parse_document(
    file_path: Path,
    doc_id: UUID,
    tenant_id: UUID,  # kept for interface / logging
    use_ocr: bool = True,  # kept for backwards-compat; Docling OCR is disabled
) -> List[ParsedBlock]:
    """
    Parse document into structured blocks using Docling, with OCR fallback.

    1. Run Docling (no OCR, tables on) with a timeout.
    2. If Docling fails or returns no elements → fallback parse (PyMuPDF text + optional OCR).
    3. Convert Docling elements into ParsedBlock instances.
    4. Optionally recover low-signal pages via selective OCR (best-effort).

    Args:
        file_path: Path to the document file.
        doc_id: Document UUID for tracking.
        tenant_id: Tenant UUID for multi-tenancy.
        use_ocr: Currently unused; OCR is handled in our own fallback.

    Returns:
        List of ParsedBlock objects representing document structure.
    """
    _ = use_ocr  # kept for interface compatibility

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Document file not found: {file_path}")

    logger.info(
        "Parsing document %s for tenant %s from %s using Docling",
        doc_id,
        tenant_id,
        file_path,
    )

    converter = _get_docling_converter()

    try:
        logger.info(
            "Starting Docling conversion for %s (timeout=%ss)...",
            file_path,
            DOCLING_CONVERSION_TIMEOUT_SEC,
        )
        result = _run_docling_with_timeout(
            converter=converter,
            file_path=file_path,
            timeout_sec=DOCLING_CONVERSION_TIMEOUT_SEC,
        )
    except concurrent.futures.TimeoutError:
        logger.error(
            "Docling conversion timed out after %ss for %s",
            DOCLING_CONVERSION_TIMEOUT_SEC,
            file_path,
        )
        blocks = _fallback_parse(file_path, doc_id)
        if blocks:
            logger.warning(
                "Using fallback parsing for document %s after Docling timeout",
                doc_id,
            )
            return blocks
        raise RuntimeError(
            f"Document parsing timed out and fallback produced no content: {file_path}"
        ) from None
    except Exception as exc:  # noqa: BLE001
        logger.error("Docling conversion failed: %s", exc, exc_info=True)
        blocks = _fallback_parse(file_path, doc_id)
        if blocks:
            logger.warning(
                "Using fallback parsing for document %s after Docling failure",
                doc_id,
            )
            return blocks
        raise RuntimeError(f"Document parsing failed: {exc}") from exc

    blocks: List[ParsedBlock] = []
    current_section_path: List[str] = []

    doc = getattr(result, "document", None)
    if not doc:
        logger.warning(
            "Docling returned no document for %s, attempting fallback parsing",
            file_path,
        )
        return _fallback_parse(file_path, doc_id)

    elements: List[Tuple[Any, int]] = []
    try:
        for element, level in doc.iterate_items():
            elements.append((element, level))
        logger.info(
            "Retrieved %d items via iterate_items() for document %s",
            len(elements),
            doc_id,
        )
    except AttributeError:
        logger.warning(
            "iterate_items() not available, trying direct elements attribute"
        )
        raw_elements = getattr(doc, "elements", None)
        if raw_elements:
            elements = [(elem, 0) for elem in raw_elements]
            logger.info(
                "Retrieved %d elements directly for document %s",
                len(elements),
                doc_id,
            )
        else:
            logger.warning(
                "No elements found via iterate_items() or direct access for %s",
                file_path,
            )
            return _fallback_parse(file_path, doc_id)

    if not elements:
        logger.warning(
            "Docling returned empty elements list for %s, attempting fallback parsing",
            file_path,
        )
        return _fallback_parse(file_path, doc_id)

    page_stats: Dict[int, Dict[str, Any]] = {}

    for element, level in elements:
        if hasattr(element, "__class__") and "Document" in element.__class__.__name__:
            continue

        block = _element_to_block(element, current_section_path, doc)
        if block:
            logger.debug(
                "Extracted block: type=%s, page=%s, text_len=%s",
                block.type,
                block.page_start,
                len(block.get_content()),
            )
            blocks.append(block)
            _accumulate_page_stats(page_stats, block)

        if getattr(element, "type", None) == "heading" and hasattr(element, "metadata"):
            heading_level = element.metadata.get("level", level or 1)
            _update_section_path(current_section_path, heading_level, element.text)

    if not blocks:
        logger.warning(
            "Docling parsed 0 blocks for %s, attempting fallback parsing",
            file_path,
        )
        return _fallback_parse(file_path, doc_id)

    # Page-level quality gate: selectively OCR sparse / clearly broken pages
    blocks = _recover_low_signal_pages(
        file_path=file_path,
        page_stats=page_stats,
        blocks=blocks,
    )

    # If only tables remain (no text), synthesize text from Docling markdown or fallback
    has_text = any(b.type == "text" for b in blocks)
    if not has_text:
        logger.warning(
            "No text blocks found for %s after Docling; synthesizing text content",
            file_path,
        )
        synthesized_blocks: List[ParsedBlock] = []

        try:
            if hasattr(doc, "to_markdown"):
                md_text = doc.to_markdown()
                if md_text and md_text.strip():
                    synthesized_blocks.append(
                        ParsedBlock(
                            type="text",
                            text=md_text,
                            page_start=1,
                            page_end=getattr(doc, "num_pages", 1) or 1,
                            language=_detect_language(md_text),
                            section_path=[],
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Docling markdown synthesis failed: %s", exc)

        if not synthesized_blocks:
            fallback_blocks = _fallback_parse(file_path, doc_id)
            synthesized_blocks.extend([b for b in fallback_blocks if b.type == "text"])

        if synthesized_blocks:
            blocks.extend(synthesized_blocks)
            blocks.sort(key=lambda b: (b.page_start, b.page_end))

    logger.info("Parsed %s blocks from document %s via Docling", len(blocks), doc_id)
    return blocks


def _element_to_block(
    element: Any,
    section_path: List[str],
    doc: Any = None,
) -> Optional[ParsedBlock]:
    """Convert a Docling element to a ParsedBlock, if applicable."""
    try:
        from docling_core.types.doc import TableItem

        if isinstance(element, TableItem):
            logger.debug("Processing TableItem")
            try:
                table_markdown = (
                    element.export_to_markdown(doc=doc)
                    if doc
                    else element.export_to_markdown()
                )
            except TypeError:
                table_markdown = element.export_to_markdown()

            block = ParsedBlock(
                type="table",
                table_markdown=table_markdown,
                page_start=getattr(element, "page_number", 1),
                page_end=getattr(element, "page_number", 1),
                section_path=section_path.copy(),
                bbox=_extract_bbox(element),
                raw_element=element,
                table_data=getattr(element, "table_data", None),
            )
            setattr(block, "_dl_element", element)
            return block
    except ImportError:
        logger.debug("docling_core not available for type checking")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Error checking TableItem: %s", exc)

    element_type = getattr(element, "type", None)

    if element_type == "paragraph":
        if not getattr(element, "text", ""):
            return None
        return ParsedBlock(
            type="text",
            text=element.text,
            page_start=getattr(element, "page_number", 1),
            page_end=getattr(element, "page_number", 1),
            section_path=section_path.copy(),
            bbox=_extract_bbox(element),
            language=_detect_language(element.text),
            raw_element=element,
        )

    if element_type == "table":
        table_md = _table_to_markdown(element)
        block = ParsedBlock(
            type="table",
            table_markdown=table_md,
            page_start=getattr(element, "page_number", 1),
            page_end=getattr(element, "page_number", 1),
            section_path=section_path.copy(),
            bbox=_extract_bbox(element),
            raw_element=element,
            table_data=getattr(element, "table_data", None),
        )
        setattr(block, "_dl_element", element)
        return block

    if element_type == "heading":
        if not getattr(element, "text", ""):
            return None
        return ParsedBlock(
            type="text",
            text=element.text,
            page_start=getattr(element, "page_number", 1),
            page_end=getattr(element, "page_number", 1),
            section_title=element.text,
            section_path=section_path.copy(),
            bbox=_extract_bbox(element),
            language=_detect_language(element.text),
            raw_element=element,
        )

    return None


def _extract_bbox(element: Any) -> Optional[List[float]]:
    """Extract bounding box from element metadata if available."""
    bbox = getattr(element, "bbox", None)
    if not bbox:
        return None
    return [float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)]


def _detect_language(text: str) -> Literal["ar", "en", "mixed"]:
    """Detect language (Arabic / English / mixed) via simple character stats."""
    if not text:
        return "en"

    arabic_chars = sum(
        1 for c in text if any(start <= c <= end for start, end in ARABIC_CHAR_RANGES)
    )
    total_alpha = sum(1 for c in text if c.isalpha())

    if total_alpha == 0:
        return "en"

    arabic_ratio = arabic_chars / total_alpha

    if arabic_ratio > ARABIC_RATIO_THRESHOLD:
        return "ar"
    if arabic_ratio > MIXED_LANG_THRESHOLD:
        return "mixed"
    return "en"


def _table_to_markdown(element: Any) -> str:
    """Convert a Docling table element to markdown format."""
    table_data = getattr(element, "table_data", None)
    if not table_data or not getattr(table_data, "rows", None):
        return "| Table data not available |"

    rows = table_data.rows
    if not rows:
        return "| Empty table |"

    md_lines: List[str] = []

    header = rows[0]
    md_lines.append("| " + " | ".join(str(cell) for cell in header) + " |")
    md_lines.append("|" + "|".join("---" for _ in header) + "|")

    for row in rows[1:]:
        md_lines.append("| " + " | ".join(str(cell) for cell in row) + " |")

    return "\n".join(md_lines)


def _update_section_path(section_path: List[str], level: int, title: str) -> None:
    """Update section path based on heading level."""
    while len(section_path) >= level:
        section_path.pop()
    section_path.append(title)


def _accumulate_page_stats(
    page_stats: Dict[int, Dict[str, Any]],
    block: ParsedBlock,
) -> None:
    """Accumulate simple page-level stats for quality gating."""
    page = block.page_start
    stats = page_stats.setdefault(
        page,
        {"chars": 0, "arabic_chars": 0, "blocks": 0, "tables": 0},
    )

    text = block.get_content()
    stats["chars"] += len(text)
    stats["arabic_chars"] += sum(
        1 for c in text if any(start <= c <= end for start, end in ARABIC_CHAR_RANGES)
    )
    stats["blocks"] += 1
    if block.type == "table":
        stats["tables"] += 1


def _recover_low_signal_pages(
    file_path: Path,
    page_stats: Dict[int, Dict[str, Any]],
    blocks: List[ParsedBlock],
) -> List[ParsedBlock]:
    """
    For pages with too little text, rerun OCR and replace/augment blocks.

    Best-practice: OCR is best-effort.
    - If PaddleOCR can't initialize (network/model hoster issues), we skip selective OCR
      rather than failing the whole parse.
    """
    suspect_pages: List[int] = []

    for page, stats in page_stats.items():
        chars = stats.get("chars", 0)
        arabic_chars = stats.get("arabic_chars", 0)
        blocks_count = stats.get("blocks", 0)
        arabic_ratio = (arabic_chars / chars) if chars else 0.0

        tables = stats.get("tables", 0)
        text_present = chars > 0 or tables > 0

        if text_present:
            continue

        if chars < PAGE_MIN_CHARS or (
            arabic_ratio < PAGE_LOW_ARABIC_RATIO and blocks_count <= 2
        ):
            suspect_pages.append(page)

    if not suspect_pages:
        return blocks

    logger.warning(
        "Detected low-signal pages %s in %s, running selective OCR",
        suspect_pages,
        file_path,
    )

    from .paddleocr_service import get_paddle_ocr_service

    paddle_service = get_paddle_ocr_service()
    if paddle_service.is_disabled:
        logger.warning("PaddleOCR disabled via env flag; skipping selective OCR")
        return blocks

    if not paddle_service.is_available() or not paddle_service.initialize_best_effort():
        logger.warning("PaddleOCR unavailable/uninitialized; skipping selective OCR")
        return blocks

    try:
        import fitz  # type: ignore[import]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF not available for selective OCR: %s", exc)
        return blocks

    try:
        doc = fitz.open(str(file_path))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to open PDF for selective OCR: %s", exc)
        return blocks

    new_blocks: List[ParsedBlock] = []
    suspect_set = set(suspect_pages)

    try:
        for page_num in range(len(doc)):
            page_index = page_num
            page_number = page_num + 1

            if page_number not in suspect_set:
                new_blocks.extend([b for b in blocks if b.page_start == page_number])
                continue

            logger.info("Selective OCR for page %s of %s", page_number, file_path.name)

            try:
                text, text_blocks = paddle_service.extract_text_from_file(
                    file_path,
                    page_num=page_index,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Selective OCR failed for page %s of %s: %s",
                    page_number,
                    file_path.name,
                    exc,
                )
                text, text_blocks = "", []

            if not text.strip():
                continue

            confidence = (
                float(np.mean([b["confidence"] for b in text_blocks]))
                if text_blocks
                else 1.0
            )
            new_blocks.append(
                ParsedBlock(
                    type="text",
                    text=text,
                    page_start=page_number,
                    page_end=page_number,
                    language=_detect_language(text),
                    confidence=confidence,
                )
            )
    finally:
        doc.close()

    # For suspect pages where OCR yielded nothing, fall back to original blocks
    existing_pages = {b.page_start for b in new_blocks}
    for page_number in suspect_set:
        if page_number in existing_pages:
            continue
        new_blocks.extend([b for b in blocks if b.page_start == page_number])

    new_blocks.sort(key=lambda b: (b.page_start, b.page_end))
    return new_blocks


def _fallback_parse(file_path: Path, doc_id: UUID) -> List[ParsedBlock]:
    """
    Fallback parsing using PyMuPDF + optional PaddleOCR.

    Best-practice: OCR is best-effort. If OCR cannot initialize, we keep any
    available text extraction from PyMuPDF instead of failing hard.
    """
    logger.info("Using fallback parsing for document %s (%s)", doc_id, file_path)

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf_fallback(file_path)
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}:
        return _parse_image_fallback(file_path)

    logger.warning("No fallback available for file type %s", suffix)
    return []


def _parse_pdf_fallback(file_path: Path) -> List[ParsedBlock]:
    """Parse PDF using PyMuPDF with optional PaddleOCR for scanned pages."""
    try:
        import fitz  # type: ignore[import]
    except ImportError:
        logger.error("PyMuPDF not available for fallback parsing")
        return []

    from .paddleocr_service import get_paddle_ocr_service

    paddle_service = get_paddle_ocr_service()

    if paddle_service.is_disabled:
        logger.warning(
            "PaddleOCR disabled via env flag; skipping OCR fallback for %s",
            file_path.name,
        )
        ocr_ready = False
    else:
        # Best practice: attempt init once; if it fails, continue without OCR
        ocr_ready = (
            paddle_service.is_available() and paddle_service.initialize_best_effort()
        )

    blocks: List[ParsedBlock] = []

    try:
        doc = fitz.open(str(file_path))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to open PDF in fallback parsing: %s", exc)
        return []

    try:
        for page_num, page in enumerate(doc):
            text = page.get_text() or ""

            if _should_use_ocr(text) and ocr_ready:
                logger.info(
                    "Fallback OCR: using PaddleOCR for page %s of %s",
                    page_num + 1,
                    file_path.name,
                )
                text = _extract_text_with_ocr(page, paddle_service)

            if not text.strip():
                continue

            blocks.append(
                ParsedBlock(
                    type="text",
                    text=text,
                    page_start=page_num + 1,
                    page_end=page_num + 1,
                    language=_detect_language(text),
                )
            )
    finally:
        doc.close()

    if not blocks:
        logger.warning("Fallback PDF parsing produced no text blocks for %s", file_path)

    return blocks


def _parse_image_fallback(file_path: Path) -> List[ParsedBlock]:
    """Parse single image file using PaddleOCR (best-effort)."""
    from .paddleocr_service import get_paddle_ocr_service

    paddle_service = get_paddle_ocr_service()
    if paddle_service.is_disabled:
        logger.warning(
            "PaddleOCR disabled via env flag; skipping image OCR for %s", file_path.name
        )
        return []

    if not paddle_service.is_available() or not paddle_service.initialize_best_effort():
        logger.warning("PaddleOCR unavailable/uninitialized for image fallback parsing")
        return []

    try:
        text, text_blocks = paddle_service.extract_text_from_file(file_path)
    except Exception as exc:  # noqa: BLE001
        logger.error("PaddleOCR failed for fallback image parsing: %s", exc)
        return []

    if not text:
        logger.warning("PaddleOCR image fallback produced empty text for %s", file_path)
        return []

    confidence = (
        float(np.mean([b["confidence"] for b in text_blocks])) if text_blocks else 1.0
    )

    return [
        ParsedBlock(
            type="text",
            text=text,
            page_start=1,
            page_end=1,
            language=_detect_language(text),
            confidence=confidence,
        ),
    ]


def _should_use_ocr(text: str) -> bool:
    """Heuristic to determine if OCR should be used based on text quality."""
    if len(text) < MIN_TEXT_LENGTH:
        return True

    words = text.split()
    if not words:
        return True

    meaningful = sum(1 for w in words if len(w) > 2 and w.isalnum())
    return meaningful < len(words) * SCANNED_PAGE_MIN_WORDS


def _extract_text_with_ocr(page: Any, paddle_service: Any) -> str:
    """
    Extract text from a PyMuPDF page using OCR.

    IMPORTANT: PyMuPDF pixmap samples are RGB/RGBA; PaddleOCR expects BGR.
    """
    try:
        import fitz  # type: ignore[import]

        mat = fitz.Matrix(PAGE_ZOOM_FACTOR, PAGE_ZOOM_FACTOR)
        pix = page.get_pixmap(matrix=mat)

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height,
            pix.width,
            pix.n,
        )

        if pix.n == 4:
            img = img[:, :, :3]

        # RGB -> BGR for PaddleOCR
        img_bgr = img[:, :, ::-1].copy()

        text, _ = paddle_service.extract_text_from_image(img_bgr)
        return text or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed for page in fallback parsing: %s", exc)
        return page.get_text() or ""
