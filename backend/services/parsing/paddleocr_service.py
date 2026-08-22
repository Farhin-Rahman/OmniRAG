"""
PaddleOCR service for Arabic/English text extraction.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_CPU_THREADS = 2
DEFAULT_Y_THRESHOLD = 20.0
CONFIDENCE_THRESHOLD = 0.3
RTL_THRESHOLD = 0.5

DEFAULT_OCR_VERSION = "PP-OCRv5"
DEFAULT_LANG = "en"

DEFAULT_PDF_ZOOM = 2.0


@dataclass(frozen=True)
class PaddleOCROptions:
    """Runtime options for PaddleOCR initialization."""

    lang: str = DEFAULT_LANG
    ocr_version: str = DEFAULT_OCR_VERSION
    cpu_threads: int = DEFAULT_CPU_THREADS
    disable_ocr: bool = False

    # If you truly want strict offline behavior, set these via env
    offline_mode: bool = False
    disable_model_source_check: bool = False

    # Optional: explicit model directory (only if you manage models yourself)
    model_dir: str | None = None

    # Performance toggles
    enable_mkldnn: bool = False
    use_textline_orientation: bool = False


class PaddleOCRService:
    """PaddleOCR wrapper for Arabic/English text extraction."""

    def __init__(self, options: PaddleOCROptions | None = None) -> None:
        self._ocr: Any | None = None
        self._options = options or self._options_from_env()

    @staticmethod
    def _options_from_env() -> PaddleOCROptions:
        """Build options from environment variables (safe defaults)."""

        def _env_bool(name: str, default: bool) -> bool:
            val = os.getenv(name)
            if val is None:
                return default
            return val.strip().lower() in {"1", "true", "yes", "y", "on"}

        def _env_int(name: str, default: int) -> int:
            val = os.getenv(name)
            if val is None or not val.strip():
                return default
            return int(val)

        return PaddleOCROptions(
            lang=os.getenv("PADDLEOCR_LANG", DEFAULT_LANG),
            ocr_version=os.getenv("PADDLEOCR_VERSION", DEFAULT_OCR_VERSION),
            cpu_threads=_env_int("PADDLEOCR_CPU_THREADS", DEFAULT_CPU_THREADS),
            disable_ocr=_env_bool("PADDLEOCR_DISABLE", False),
            offline_mode=_env_bool("PADDLEX_OFFLINE_MODE", False),
            disable_model_source_check=_env_bool("DISABLE_MODEL_SOURCE_CHECK", False),
            model_dir=os.getenv("PADDLEOCR_MODEL_DIR") or None,
            enable_mkldnn=_env_bool("PADDLEOCR_ENABLE_MKLDNN", False),
            use_textline_orientation=_env_bool(
                "PADDLEOCR_USE_TEXTLINE_ORIENTATION", False
            ),
        )

    @property
    def is_initialized(self) -> bool:
        """True if OCR engine is initialized."""
        return self._ocr is not None

    @property
    def is_disabled(self) -> bool:
        """True if PaddleOCR was explicitly disabled via env/config."""
        return bool(self._options.disable_ocr)

    def initialize_best_effort(self) -> bool:
        """
        Try to initialize OCR. Return False instead of raising if it fails.

        This is important in pipelines like yours:
        Docling may still extract useful content even if OCR is unavailable.
        """
        if self.is_disabled:
            logger.warning("PaddleOCR disabled via PADDLEOCR_DISABLE=1; skipping init")
            return False

        if self.is_initialized:
            return True

        try:
            self._initialize()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PaddleOCR init failed (best-effort): %s", exc, exc_info=True
            )
            self._ocr = None
            return False

    def _initialize(self) -> None:
        """Initialize PaddleOCR lazily."""
        if self.is_initialized:
            return

        # Set environment variables to prevent segfaults (especially on ARM64)
        os.environ["FLAGS_use_mkldnn"] = "0"
        os.environ["FLAGS_use_xdnn"] = "0"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["OPENBLAS_NUM_THREADS"] = "1"
        os.environ["MKL_NUM_THREADS"] = "1"
        os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
        os.environ["GOTOBLAS_NUM_THREADS"] = "1"

        # Additional flags for ARM64 stability
        os.environ["PADDLE_USE_MKL"] = "0"
        os.environ["FLAGS_enable_parallel_graph"] = "0"

        try:
            from paddleocr import PaddleOCR  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("PaddleOCR is required (pip install paddleocr)") from exc

        # IMPORTANT:
        # - Do NOT force offline env vars by default.
        # - Only set them if explicitly requested by env/options.
        if self._options.offline_mode:
            os.environ["PADDLEX_OFFLINE_MODE"] = "True"

        if self._options.disable_model_source_check:
            os.environ["DISABLE_MODEL_SOURCE_CHECK"] = "True"

        # Set PADDLEX_HOME if provided in environment (for proper cache/temp location)
        paddlex_home = os.environ.get("PADDLEX_HOME")
        if paddlex_home:
            os.environ["PADDLEX_HOME"] = paddlex_home
            logger.info("Using PADDLEX_HOME=%s", paddlex_home)

        # If you mount caches, also ensure HOME points to a writable location.
        # (In Docker, you already use /home/appuser.)
        logger.info(
            "Initializing PaddleOCR (version=%s, lang=%s, cpu_threads=%s, offline=%s, disable_source_check=%s, model_dir=%s)",
            self._options.ocr_version,
            self._options.lang,
            self._options.cpu_threads,
            self._options.offline_mode,
            self._options.disable_model_source_check,
            self._options.model_dir,
        )

        init_params: dict[str, Any] = {
            "ocr_version": self._options.ocr_version,
            "lang": self._options.lang,
            "device": "cpu",
            "cpu_threads": self._options.cpu_threads,
            "enable_mkldnn": self._options.enable_mkldnn,
            # PP-OCRv5 specific parameters from documentation
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": self._options.use_textline_orientation,
            # Force mobile models instead of server models
            "det_limit_side_len": 960,  # Mobile model default
            "det_limit_type": "max",
        }

        # Only pass model_dir if you really manage models yourself
        if self._options.model_dir:
            init_params["model_dir"] = self._options.model_dir

        self._ocr = PaddleOCR(**init_params)

    def extract_text_from_image(
        self,
        image_bgr: np.ndarray,
        merge_lines: bool = True,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Extract text from a BGR image using PaddleOCR.

        Returns:
            (full_text, blocks) where blocks include bbox + confidence.
        """
        if not self.initialize_best_effort():
            return "", []

        if image_bgr.size == 0:
            logger.warning("Empty image provided to PaddleOCR")
            return "", []

        image_bgr = self._normalize_image(image_bgr)

        lines = self._run_ocr(image_bgr)
        if not lines:
            return "", []

        blocks = self._process_ocr_results(lines)
        blocks = [b for b in blocks if b["confidence"] >= CONFIDENCE_THRESHOLD]
        if not blocks:
            return "", []

        full_text = (
            self._merge_lines_to_paragraphs(blocks)
            if merge_lines
            else "\n".join(b["text"] for b in blocks)
        )
        return full_text, blocks

    def extract_text_from_file(
        self,
        file_path: Path,
        page_num: int | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Extract text from an image file or a single PDF page."""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_from_pdf_page(file_path, page_num or 0)

        if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}:
            return self._extract_from_image_file(file_path)

        raise ValueError(f"Unsupported file type for OCR: {suffix}")

    def _extract_from_image_file(
        self, file_path: Path
    ) -> tuple[str, list[dict[str, Any]]]:
        try:
            import cv2  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("OpenCV required (opencv-python-headless)") from exc

        image_bgr = cv2.imread(str(file_path))
        if image_bgr is None:
            raise ValueError(f"Failed to load image: {file_path}")

        return self.extract_text_from_image(image_bgr)

    def _extract_from_pdf_page(
        self, pdf_path: Path, page_num: int
    ) -> tuple[str, list[dict[str, Any]]]:
        try:
            import fitz  # type: ignore[import]
        except ImportError as exc:
            raise ImportError("PyMuPDF required (pip install pymupdf)") from exc

        with fitz.open(str(pdf_path)) as doc:
            if not (0 <= page_num < len(doc)):
                raise ValueError(
                    f"Page {page_num} not found in PDF (total pages: {len(doc)})"
                )

            page = doc[page_num]
            mat = fitz.Matrix(DEFAULT_PDF_ZOOM, DEFAULT_PDF_ZOOM)
            pix = page.get_pixmap(matrix=mat)

            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                img = img[:, :, :3]

            # PyMuPDF gives RGB; convert to BGR for PaddleOCR
            image_bgr = img[:, :, ::-1].copy()

        return self.extract_text_from_image(image_bgr)

    def _run_ocr(self, image_bgr: np.ndarray) -> list[Any]:
        """
        Run OCR and normalize output into a list of lines.
        """
        if self._ocr is None:
            return []

        # Use ocr() method - works for both PaddleOCR 2.x and 3.x
        if hasattr(self._ocr, "ocr"):
            try:
                result = self._ocr.ocr(image_bgr)
                return self._normalize_result(result)
            except Exception as e:
                logger.error("PaddleOCR ocr() failed: %s", e, exc_info=True)
                return []

        # Fallback to predict() method if ocr() not available
        if hasattr(self._ocr, "predict"):
            try:
                result = self._ocr.predict(input=image_bgr)
                return self._normalize_result(result)
            except Exception as e:
                logger.error("PaddleOCR predict() failed: %s", e, exc_info=True)
                return []

        raise RuntimeError("Unsupported PaddleOCR instance: missing ocr()/predict()")

    @staticmethod
    def _normalize_result(result: Any) -> list[Any]:
        """Normalize OCR output to a simple list of lines."""
        if result is None:
            return []

        # If generator/iterator, materialize once
        if not isinstance(result, list):
            try:
                result = list(result)
            except TypeError:
                # not iterable
                return []

        if not result:
            return []

        # PaddleOCR 3.x returns a list with OCRResult object or dict per image
        if len(result) > 0:
            first = result[0]

            # Handle OCRResult object (PaddleOCR 3.x)
            if (
                hasattr(first, "rec_texts")
                and hasattr(first, "rec_scores")
                and hasattr(first, "rec_polys")
            ):
                rec_texts = first.rec_texts
                rec_scores = first.rec_scores
                rec_polys = first.rec_polys

                # Convert to old format: [[bbox_points], (text, score)]
                lines = []
                for text, score, poly in zip(rec_texts, rec_scores, rec_polys):
                    if text:
                        lines.append([poly, (text, score)])

                return lines

            # Handle dict format (alternative PaddleOCR 3.x format)
            if isinstance(first, dict):
                rec_texts = first.get("rec_texts", [])
                rec_scores = first.get("rec_scores", [])
                rec_polys = first.get("rec_polys", [])

                # Convert to old format: [[bbox_points], (text, score)]
                lines = []
                for text, score, poly in zip(rec_texts, rec_scores, rec_polys):
                    if text:
                        lines.append([poly, (text, score)])

                return lines

            # Some shapes look like: [ [line, line, ...] ]
            if isinstance(first, list):
                return first

        return result

    @staticmethod
    def _normalize_image(image: np.ndarray) -> np.ndarray:
        """Ensure image is HxWx3 BGR."""
        if image.ndim == 2:
            return np.stack([image] * 3, axis=-1)

        if image.ndim == 3 and image.shape[2] == 4:
            return image[:, :, :3]

        return image

    @staticmethod
    def _process_ocr_results(ocr_lines: list[Any]) -> list[dict[str, Any]]:
        """Convert raw output to blocks with bbox + confidence."""
        blocks: list[dict[str, Any]] = []

        for line in ocr_lines:
            if not line or len(line) < 2:
                continue

            bbox_points = line[0]
            text = line[1][0]
            confidence = float(line[1][1])

            if not text:
                continue

            x_coords = [float(pt[0]) for pt in bbox_points]
            y_coords = [float(pt[1]) for pt in bbox_points]
            bbox_rect = [min(x_coords), min(y_coords), max(x_coords), max(y_coords)]

            blocks.append(
                {
                    "text": text,
                    "bbox": bbox_rect,
                    "confidence": confidence,
                    "polygon": bbox_points,
                }
            )

        return blocks

    def _merge_lines_to_paragraphs(
        self,
        blocks: list[dict[str, Any]],
        y_threshold: float = DEFAULT_Y_THRESHOLD,
    ) -> str:
        if not blocks:
            return ""

        sorted_blocks = sorted(blocks, key=lambda b: b["bbox"][1])
        paragraphs: list[str] = []
        current: list[str] = [sorted_blocks[0]["text"]]
        last_bottom = sorted_blocks[0]["bbox"][3]

        for block in sorted_blocks[1:]:
            top = block["bbox"][1]

            if top - last_bottom <= y_threshold:
                if self._is_rtl_text(block["text"]):
                    current.append(block["text"])
                else:
                    current.append(" " + block["text"])
            else:
                paragraphs.append("".join(current))
                current = [block["text"]]

            last_bottom = block["bbox"][3]

        paragraphs.append("".join(current))
        return "\n\n".join(paragraphs)

    @staticmethod
    def _is_rtl_text(text: str) -> bool:
        if not text:
            return False

        arabic_chars = sum(
            1 for c in text if "\u0600" <= c <= "\u06ff" or "\u0750" <= c <= "\u077f"
        )
        return arabic_chars > len(text) * RTL_THRESHOLD

    def is_available(self) -> bool:
        """True if paddleocr package is importable (does not guarantee network/model availability)."""
        if self.is_disabled:
            return False
        try:
            import paddleocr  # type: ignore[import]  # noqa: F401

            return True
        except ImportError:
            return False


_paddle_ocr_service: PaddleOCRService | None = None


def get_paddle_ocr_service() -> PaddleOCRService:
    """Singleton PaddleOCR service."""
    global _paddle_ocr_service  # noqa: PLW0603
    if _paddle_ocr_service is None:
        _paddle_ocr_service = PaddleOCRService()
    return _paddle_ocr_service
