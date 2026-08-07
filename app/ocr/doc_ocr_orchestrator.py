"""OCR engine orchestrator for Document Intelligence.

Integrates PaddleOCR, EasyOCR, and Tesseract with OpenCV document preprocessing.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

from app.core.config import settings
from app.ocr.doc_preprocessor import DocumentPreprocessor
from app.ocr.paddleocr_engine import PaddleOCREngine
from app.ocr.easyocr_engine import EasyOCREngine
from app.ocr.tesseract_engine import TesseractOCREngine

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}


class DocOCRResult:
    """Consolidated OCR extraction result."""

    def __init__(
        self,
        text: str,
        confidence: float,
        engine: str,
        preprocessing_applied: bool,
        error: Optional[str] = None,
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.engine = engine
        self.preprocessing_applied = preprocessing_applied
        self.error = error

    @property
    def is_success(self) -> bool:
        return bool(self.text) and self.error is None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "engine": self.engine,
            "preprocessing_applied": self.preprocessing_applied,
            "char_count": len(self.text),
            "error": self.error,
        }


class DocOCROrchestrator:
    """Manages the fallback OCR execution pipeline."""

    def __init__(self) -> None:
        self.preprocessor = DocumentPreprocessor(
            deskew=settings.OCR_PREPROCESSING_ENABLED,
            denoise=settings.OCR_PREPROCESSING_ENABLED,
            enhance_contrast=settings.OCR_PREPROCESSING_ENABLED,
            remove_shadows=settings.OCR_PREPROCESSING_ENABLED,
            correct_perspective=settings.OCR_PREPROCESSING_ENABLED,
            sharpen=settings.OCR_PREPROCESSING_ENABLED,
            binarize=False,  # Keep grayscale/color detail for OCR models
        )
        self.paddle = PaddleOCREngine()
        self.easyocr = EasyOCREngine()
        self.tesseract = TesseractOCREngine()
        self.fallback_chain = settings.OCR_FALLBACK_CHAIN
        self.preference = settings.OCR_ENGINE_PREFERENCE
        self._availability_cache: dict[str, bool] = {}

    def extract_text(self, file_path: str) -> DocOCRResult:
        """Run full preprocessing and OCR on a document image."""
        _, ext = os.path.splitext(file_path.lower())
        if ext not in IMAGE_EXTENSIONS:
            return DocOCRResult(
                text="", confidence=0.0, engine="none", preprocessing_applied=False,
                error=f"File extension {ext} is not supported as an image for OCR."
            )

        preprocessed_path = file_path
        preprocessing_applied = False

        if settings.OCR_PREPROCESSING_ENABLED:
            try:
                preprocessed_path = self.preprocessor.preprocess_image(file_path)
                preprocessing_applied = True
            except Exception as exc:
                logger.warning("OCR image preprocessing failed: %s. Using original.", exc)

        order = self._get_execution_order()
        for engine_name in order:
            if not self._is_engine_available(engine_name):
                logger.info("OCR Engine '%s' is not available, trying next in chain.", engine_name)
                continue

            try:
                text, conf = self._run_engine(engine_name, preprocessed_path)
                if len(text.strip()) > 10:
                    self._cleanup_temp(preprocessed_path, file_path)
                    return DocOCRResult(
                        text=text,
                        confidence=conf,
                        engine=engine_name,
                        preprocessing_applied=preprocessing_applied,
                    )
            except Exception as exc:
                logger.error("OCR extraction with engine '%s' failed: %s", engine_name, exc)

        self._cleanup_temp(preprocessed_path, file_path)
        return DocOCRResult(
            text="", confidence=0.0, engine="none", preprocessing_applied=preprocessing_applied,
            error="All configured OCR engines failed or produced empty outputs."
        )

    def extract_from_bytes(self, image_bytes: bytes, ext: str = ".png") -> DocOCRResult:
        """Save image bytes to temporary file, run OCR, and clean up."""
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            return self.extract_text(tmp_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Engine runners
    # ------------------------------------------------------------------

    def _run_engine(self, name: str, path: str) -> tuple[str, float]:
        if name == "paddle":
            return self.paddle.extract_text_with_confidence(path)
        elif name == "easyocr":
            return self.easyocr.extract_text_with_confidence(path)
        elif name == "tesseract":
            return self.tesseract.extract_text_with_confidence(path)
        return "", 0.0

    def _is_engine_available(self, name: str) -> bool:
        if name not in self._availability_cache:
            if name == "paddle":
                self._availability_cache["paddle"] = self.paddle.is_available
            elif name == "easyocr":
                self._availability_cache["easyocr"] = self.easyocr.is_available
            elif name == "tesseract":
                self._availability_cache["tesseract"] = self.tesseract.is_available
            else:
                self._availability_cache[name] = False
        return self._availability_cache[name]

    def _get_execution_order(self) -> list[str]:
        if self.preference == "auto":
            return self.fallback_chain
        # Preferred engine first, then fallbacks
        return [self.preference] + [e for e in self.fallback_chain if e != self.preference]

    @staticmethod
    def _cleanup_temp(temp_path: str, orig_path: str) -> None:
        if temp_path != orig_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def get_status(self) -> dict[str, bool]:
        return {
            "paddle": self._is_engine_available("paddle"),
            "easyocr": self._is_engine_available("easyocr"),
            "tesseract": self._is_engine_available("tesseract"),
        }


# Singleton accessor
_orchestrator: DocOCROrchestrator | None = None


def get_ocr_orchestrator() -> DocOCROrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = DocOCROrchestrator()
    return _orchestrator
