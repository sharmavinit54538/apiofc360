"""PaddleOCR engine adapter.

PaddleOCR provides state-of-the-art OCR accuracy, especially for
multi-language documents and complex layouts.

Install: pip install paddlepaddle paddleocr
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from paddleocr import PaddleOCR as _PaddleOCR
    PADDLE_AVAILABLE = True
except ImportError:
    PADDLE_AVAILABLE = False
    logger.info("PaddleOCR not installed — engine disabled")


class PaddleOCREngine:
    """Wrapper around PaddleOCR for document text extraction."""

    _instance: Optional["PaddleOCREngine"] = None
    _ocr: Optional[object] = None

    def __new__(cls) -> "PaddleOCREngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_ocr(self) -> object:
        """Lazy-initialize PaddleOCR (heavy model load)."""
        if self._ocr is None and PADDLE_AVAILABLE:
            try:
                self._ocr = _PaddleOCR(
                    use_angle_cls=True,
                    lang="en",
                    use_gpu=False,  # CPU inference by default
                    show_log=False,
                    enable_mkldnn=False,  # Avoid conflicts in some envs
                )
                logger.info("PaddleOCR initialized successfully")
            except Exception as exc:
                logger.error("PaddleOCR initialization failed: %s", exc)
        return self._ocr

    @property
    def is_available(self) -> bool:
        """Return True if PaddleOCR is installed and initialized."""
        return PADDLE_AVAILABLE

    def extract_text(self, image_path: str) -> str:
        """Extract text from an image file using PaddleOCR.

        Returns concatenated text lines, or empty string on failure.
        """
        if not PADDLE_AVAILABLE:
            return ""

        ocr = self._get_ocr()
        if ocr is None:
            return ""

        try:
            results = ocr.ocr(image_path, cls=True)
            if not results:
                return ""

            lines: list[str] = []
            for page_result in results:
                if page_result is None:
                    continue
                for line in page_result:
                    if line and len(line) >= 2:
                        text_info = line[1]
                        if isinstance(text_info, (list, tuple)) and len(text_info) >= 1:
                            text = str(text_info[0]).strip()
                            if text:
                                lines.append(text)

            extracted = "\n".join(lines)
            logger.debug("PaddleOCR extracted %d chars from %s", len(extracted), image_path)
            return extracted

        except Exception as exc:
            logger.error("PaddleOCR extraction failed for %s: %s", image_path, exc)
            return ""

    def extract_text_with_confidence(self, image_path: str) -> tuple[str, float]:
        """Extract text and return (text, average_confidence)."""
        if not PADDLE_AVAILABLE:
            return "", 0.0

        ocr = self._get_ocr()
        if ocr is None:
            return "", 0.0

        try:
            results = ocr.ocr(image_path, cls=True)
            if not results:
                return "", 0.0

            lines: list[str] = []
            confidences: list[float] = []

            for page_result in results:
                if page_result is None:
                    continue
                for line in page_result:
                    if line and len(line) >= 2:
                        text_info = line[1]
                        if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                            text = str(text_info[0]).strip()
                            conf = float(text_info[1])
                            if text:
                                lines.append(text)
                                confidences.append(conf)

            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            return "\n".join(lines), avg_confidence

        except Exception as exc:
            logger.error("PaddleOCR confidence extraction failed: %s", exc)
            return "", 0.0
