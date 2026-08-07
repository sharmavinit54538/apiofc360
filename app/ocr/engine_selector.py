"""OCR Engine Selector — intelligently selects and orchestrates OCR engines.

Selection strategy:
1. If preference='auto': probe each engine for availability and pick best
2. If preference set: use that engine, fall back to next available in chain
3. Runs image preprocessing before OCR
4. Returns confidence-annotated results
5. Caches engine availability probes (no repeated checks)
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

from app.core.config import settings
from app.ocr.image_preprocessor import ImagePreprocessor
from app.ocr.paddleocr_engine import PaddleOCREngine
from app.ocr.easyocr_engine import EasyOCREngine
from app.ocr.tesseract_engine import TesseractOCREngine

logger = logging.getLogger(__name__)

# Image file extensions that need OCR
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".gif", ".webp"}
DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx"}


class OCRResult:
    """Structured OCR extraction result."""

    def __init__(
        self,
        text: str,
        confidence: float,
        engine_used: str,
        preprocessing_applied: bool,
        error: Optional[str] = None,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.engine_used = engine_used
        self.preprocessing_applied = preprocessing_applied
        self.error = error

    @property
    def success(self) -> bool:
        return bool(self.text) and not self.error

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "engine_used": self.engine_used,
            "preprocessing_applied": self.preprocessing_applied,
            "char_count": len(self.text),
            "error": self.error,
        }


class OCREngineSelector:
    """Auto-selecting multi-engine OCR orchestrator."""

    def __init__(self) -> None:
        self._preprocessor = ImagePreprocessor(
            deskew=settings.OCR_PREPROCESSING_ENABLED,
            denoise=settings.OCR_PREPROCESSING_ENABLED,
            contrast_enhance=settings.OCR_PREPROCESSING_ENABLED,
            shadow_remove=settings.OCR_PREPROCESSING_ENABLED,
            binarize=settings.OCR_PREPROCESSING_ENABLED,
            border_remove=settings.OCR_PREPROCESSING_ENABLED,
        )
        self._paddle = PaddleOCREngine()
        self._easyocr = EasyOCREngine()
        self._tesseract = TesseractOCREngine()
        self._engine_priority = settings.OCR_FALLBACK_CHAIN
        self._preference = settings.OCR_ENGINE_PREFERENCE
        self._availability_cache: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_text_from_file(self, file_path: str) -> OCRResult:
        """Extract text from any supported file (image or document).

        For non-image files, returns empty result (handled by document parsers).
        """
        _, ext = os.path.splitext(file_path.lower())

        if ext not in IMAGE_EXTENSIONS:
            return OCRResult(
                text="",
                confidence=0.0,
                engine_used="none",
                preprocessing_applied=False,
                error=f"File type {ext} is not an image — use document parser",
            )

        return self._extract_from_image(file_path)

    def extract_text_from_image_bytes(self, image_bytes: bytes, ext: str = ".jpg") -> OCRResult:
        """Extract text from raw image bytes."""
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            return self._extract_from_image(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # Internal extraction logic
    # ------------------------------------------------------------------

    def _extract_from_image(self, image_path: str) -> OCRResult:
        """Run preprocessing + OCR on an image file."""
        # Step 1: preprocess
        preprocessed_path = image_path
        preprocessing_applied = False

        if settings.OCR_PREPROCESSING_ENABLED:
            try:
                preprocessed_path = self._preprocessor.preprocess(image_path)
                preprocessing_applied = True
            except Exception as exc:
                logger.warning("Preprocessing failed, using raw image: %s", exc)

        # Step 2: select and run engine(s)
        engines_to_try = self._get_engine_order()

        for engine_name in engines_to_try:
            result = self._try_engine(engine_name, preprocessed_path)
            if result.success and len(result.text.strip()) > 20:
                result.preprocessing_applied = preprocessing_applied
                # Cleanup temp preprocessed file
                if preprocessing_applied and preprocessed_path != image_path:
                    try:
                        os.unlink(preprocessed_path)
                    except OSError:
                        pass
                return result
            logger.info(
                "Engine '%s' yielded insufficient text (%d chars), trying next",
                engine_name, len(result.text)
            )

        # All engines failed or yielded too little text
        if preprocessing_applied and preprocessed_path != image_path:
            try:
                os.unlink(preprocessed_path)
            except OSError:
                pass

        return OCRResult(
            text="",
            confidence=0.0,
            engine_used="none",
            preprocessing_applied=preprocessing_applied,
            error="All OCR engines failed to extract sufficient text",
        )

    def _try_engine(self, engine_name: str, image_path: str) -> OCRResult:
        """Run a single OCR engine and return result."""
        try:
            if engine_name == "paddle":
                if not self._is_available("paddle"):
                    return OCRResult("", 0.0, "paddle", False, "PaddleOCR not available")
                text, conf = self._paddle.extract_text_with_confidence(image_path)
                return OCRResult(text, conf, "paddle", False)

            elif engine_name == "easyocr":
                if not self._is_available("easyocr"):
                    return OCRResult("", 0.0, "easyocr", False, "EasyOCR not available")
                text, conf = self._easyocr.extract_text_with_confidence(image_path)
                return OCRResult(text, conf, "easyocr", False)

            elif engine_name == "tesseract":
                if not self._is_available("tesseract"):
                    return OCRResult("", 0.0, "tesseract", False, "Tesseract not available")
                text, conf = self._tesseract.extract_text_with_confidence(image_path)
                return OCRResult(text, conf, "tesseract", False)

            else:
                return OCRResult("", 0.0, engine_name, False, f"Unknown engine: {engine_name}")

        except Exception as exc:
            logger.error("Engine '%s' raised exception: %s", engine_name, exc)
            return OCRResult("", 0.0, engine_name, False, str(exc))

    def _is_available(self, engine_name: str) -> bool:
        """Check engine availability (cached)."""
        if engine_name not in self._availability_cache:
            if engine_name == "paddle":
                self._availability_cache["paddle"] = self._paddle.is_available
            elif engine_name == "easyocr":
                self._availability_cache["easyocr"] = self._easyocr.is_available
            elif engine_name == "tesseract":
                self._availability_cache["tesseract"] = self._tesseract.is_available
            else:
                self._availability_cache[engine_name] = False
        return self._availability_cache[engine_name]

    def _get_engine_order(self) -> list[str]:
        """Return the ordered list of engines to try based on preference."""
        if self._preference == "auto":
            return self._engine_priority
        # Specific preference: try preferred first, then fallback chain
        priority = [self._preference] + [
            e for e in self._engine_priority if e != self._preference
        ]
        return priority

    def get_engine_status(self) -> dict[str, bool]:
        """Return availability status of all OCR engines."""
        return {
            "paddle": self._is_available("paddle"),
            "easyocr": self._is_available("easyocr"),
            "tesseract": self._is_available("tesseract"),
            "preprocessing": True,  # OpenCV availability is checked inside
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_ocr_selector: Optional[OCREngineSelector] = None


def get_ocr_selector() -> OCREngineSelector:
    """Return the global OCR engine selector singleton."""
    global _ocr_selector
    if _ocr_selector is None:
        _ocr_selector = OCREngineSelector()
    return _ocr_selector
