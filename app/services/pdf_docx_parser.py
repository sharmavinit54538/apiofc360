"""Service for extracting raw text from PDF, DOCX, and Image documents locally."""

from __future__ import annotations

import logging
import os
from pypdf import PdfReader
from docx import Document

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_path: str) -> str:
    """Extract raw text from PDF file."""
    try:
        reader = PdfReader(file_path)
        text_list = []
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_list.append(t)
        return "\n".join(text_list)
    except Exception as exc:
        logger.error("extract_text_from_pdf failed | path=%s | exc=%s", file_path, exc)
        return ""


def extract_text_from_docx(file_path: str) -> str:
    """Extract raw text from DOCX document."""
    try:
        doc = Document(file_path)
        text_list = []
        for para in doc.paragraphs:
            if para.text:
                text_list.append(para.text)
        return "\n".join(text_list)
    except Exception as exc:
        logger.error("extract_text_from_docx failed | path=%s | exc=%s", file_path, exc)
        return ""


def extract_text_from_image(file_path: str) -> str:
    """Extract text from image files using Tesseract OCR / PIL."""
    filename = os.path.basename(file_path)
    logger.info("OCR Image Extraction | path=%s", filename)
    try:
        from PIL import Image
        import pytesseract
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image)
        return text.strip()
    except Exception as exc:
        logger.warning("OCR image extraction failed or engine unavailable | path=%s | error=%s", filename, exc)
        return ""


def extract_document_text(file_path: str) -> str:
    """Detect file type and extract text cleanly."""
    _, ext = os.path.splitext(file_path.lower())
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in {".docx", ".doc"}:
        return extract_text_from_docx(file_path)
    elif ext in {".png", ".jpg", ".jpeg"}:
        return extract_text_from_image(file_path)
    return ""
