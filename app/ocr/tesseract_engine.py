"""Tesseract OCR engine adapter.

Tesseract is the gold-standard open-source OCR engine.
Excellent for clean, high-contrast document images.

Install: pip install pytesseract
Also requires Tesseract binary:
  Windows: https://github.com/UB-Mannheim/tesseract/wiki
  Linux: apt-get install tesseract-ocr
  macOS: brew install tesseract
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image

    TESSERACT_AVAILABLE = True

    # Allow configuring tesseract path via environment variable
    tesseract_cmd = os.environ.get("TESSERACT_CMD", "")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

except ImportError:
    TESSERACT_AVAILABLE = False
    logger.info("pytesseract not installed — Tesseract engine disabled")


# Tesseract page segmentation modes
_PSM_AUTO = 3          # Fully automatic page segmentation
_PSM_SINGLE_COLUMN = 4 # Assume a single column of text
_PSM_SINGLE_BLOCK = 6  # Assume a single uniform block of text


class TesseractOCREngine:
    """Wrapper around pytesseract for document text extraction."""

    @property
    def is_available(self) -> bool:
        if not TESSERACT_AVAILABLE:
            return False
        # Verify tesseract binary is accessible
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def extract_text(self, image_path: str) -> str:
        """Extract text from an image file using Tesseract.

        Tries multiple PSM configs and returns the best result.
        """
        if not TESSERACT_AVAILABLE:
            return ""

        try:
            img = Image.open(image_path)
        except Exception as exc:
            logger.error("Tesseract cannot open image %s: %s", image_path, exc)
            return ""

        best_text = ""
        best_length = 0

        configs = [
            f"--psm {_PSM_AUTO} --oem 3",
            f"--psm {_PSM_SINGLE_COLUMN} --oem 3",
            f"--psm {_PSM_SINGLE_BLOCK} --oem 3",
        ]

        for config in configs:
            try:
                text = pytesseract.image_to_string(img, lang="eng", config=config)
                text = text.strip()
                if len(text) > best_length:
                    best_text = text
                    best_length = len(text)
            except Exception as exc:
                logger.debug("Tesseract config '%s' failed: %s", config, exc)
                continue

        logger.debug("Tesseract extracted %d chars from %s", len(best_text), image_path)
        return best_text

    def extract_text_with_confidence(self, image_path: str) -> tuple[str, float]:
        """Extract text and compute average word confidence."""
        if not TESSERACT_AVAILABLE:
            return "", 0.0

        try:
            img = Image.open(image_path)
            data = pytesseract.image_to_data(
                img, lang="eng",
                config=f"--psm {_PSM_AUTO} --oem 3",
                output_type=pytesseract.Output.DICT,
            )

            texts = []
            confidences = []
            for i, conf in enumerate(data["conf"]):
                try:
                    conf_val = int(conf)
                except (ValueError, TypeError):
                    continue
                if conf_val > 0:  # -1 means no text
                    word = data["text"][i].strip()
                    if word:
                        texts.append(word)
                        confidences.append(conf_val / 100.0)

            extracted = " ".join(texts)
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            return extracted, avg_conf

        except Exception as exc:
            logger.error("Tesseract confidence extraction failed: %s", exc)
            return self.extract_text(image_path), 0.5

    def get_bounding_boxes(self, image_path: str) -> list[dict]:
        """Extract text with bounding box coordinates."""
        if not TESSERACT_AVAILABLE:
            return []
        try:
            img = Image.open(image_path)
            data = pytesseract.image_to_data(
                img, lang="eng",
                config=f"--psm {_PSM_AUTO} --oem 3",
                output_type=pytesseract.Output.DICT,
            )
            boxes = []
            for i, conf in enumerate(data["conf"]):
                try:
                    conf_val = int(conf)
                except (ValueError, TypeError):
                    continue
                if conf_val > 30:
                    word = data["text"][i].strip()
                    if word:
                        boxes.append({
                            "text": word,
                            "confidence": conf_val / 100.0,
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                        })
            return boxes
        except Exception as exc:
            logger.error("Tesseract bounding box extraction failed: %s", exc)
            return []
