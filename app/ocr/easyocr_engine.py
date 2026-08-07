"""EasyOCR engine adapter.

EasyOCR supports 80+ languages and provides excellent accuracy for
printed text in resumes, certificates, and ID documents.

Install: pip install easyocr
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import easyocr as _easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.info("EasyOCR not installed — engine disabled")


class EasyOCREngine:
    """Wrapper around EasyOCR for document text extraction."""

    _instance: Optional["EasyOCREngine"] = None
    _reader: Optional[object] = None

    def __new__(cls) -> "EasyOCREngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_reader(self) -> object:
        """Lazy-initialize EasyOCR reader (heavy model load)."""
        if self._reader is None and EASYOCR_AVAILABLE:
            try:
                self._reader = _easyocr.Reader(
                    ["en"],
                    gpu=False,
                    download_enabled=True,
                    verbose=False,
                )
                logger.info("EasyOCR reader initialized successfully")
            except Exception as exc:
                logger.error("EasyOCR reader initialization failed: %s", exc)
        return self._reader

    @property
    def is_available(self) -> bool:
        return EASYOCR_AVAILABLE

    def extract_text(self, image_path: str) -> str:
        """Extract text from an image using EasyOCR.

        Returns concatenated text, or empty string on failure.
        """
        if not EASYOCR_AVAILABLE:
            return ""

        reader = self._get_reader()
        if reader is None:
            return ""

        try:
            results = reader.readtext(image_path, detail=1, paragraph=False)
            if not results:
                return ""

            # Sort by vertical position (top to bottom, left to right)
            results_sorted = sorted(results, key=lambda r: (r[0][0][1], r[0][0][0]))

            lines = [text.strip() for _, text, _ in results_sorted if text.strip()]
            extracted = "\n".join(lines)
            logger.debug("EasyOCR extracted %d chars from %s", len(extracted), image_path)
            return extracted

        except Exception as exc:
            logger.error("EasyOCR extraction failed for %s: %s", image_path, exc)
            return ""

    def extract_text_with_confidence(self, image_path: str) -> tuple[str, float]:
        """Extract text and return (text, average_confidence)."""
        if not EASYOCR_AVAILABLE:
            return "", 0.0

        reader = self._get_reader()
        if reader is None:
            return "", 0.0

        try:
            results = reader.readtext(image_path, detail=1, paragraph=False)
            if not results:
                return "", 0.0

            results_sorted = sorted(results, key=lambda r: (r[0][0][1], r[0][0][0]))
            lines = []
            confidences = []
            for _, text, conf in results_sorted:
                if text.strip():
                    lines.append(text.strip())
                    confidences.append(float(conf))

            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            return "\n".join(lines), avg_confidence

        except Exception as exc:
            logger.error("EasyOCR confidence extraction failed: %s", exc)
            return "", 0.0
