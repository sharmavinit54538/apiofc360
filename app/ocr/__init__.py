"""OCR Engine package — auto-selecting multi-engine OCR with image preprocessing."""

from app.ocr.engine_selector import OCREngineSelector, get_ocr_selector
from app.ocr.image_preprocessor import ImagePreprocessor

__all__ = ["OCREngineSelector", "get_ocr_selector", "ImagePreprocessor"]
