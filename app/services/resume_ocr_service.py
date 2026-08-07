"""Resume OCR Service for extracting raw text from PDF, DOCX, DOC, PNG, JPG, JPEG, and TIFF files."""

from __future__ import annotations

import io
import logging
import os
from typing import Any

from app.core.exceptions import AppException
from app.services.google_document_ai_service import GoogleDocumentAIService

logger = logging.getLogger(__name__)


class ResumeOCRService:
    """Service for extracting text from resume files using Google Document AI and fallback parsers."""

    def __init__(self, doc_ai_service: GoogleDocumentAIService | None = None) -> None:
        self.doc_ai_service = doc_ai_service or GoogleDocumentAIService()

    async def extract_text(self, file_bytes: bytes, file_name: str, mime_type: str) -> dict[str, Any]:
        """Extract full raw text from uploaded resume using Document AI with robust format fallbacks."""
        ext = os.path.splitext(file_name)[1].lower()
        logger.info("Extracting resume text | file_name=%s | ext=%s | mime=%s", file_name, ext, mime_type)

        # 1. Try Google Document AI if configured
        try:
            doc_ai_result = await self.doc_ai_service.process_document(file_bytes, mime_type)
            document_obj = doc_ai_result.get("document")
            extracted_text = getattr(document_obj, "text", "") or ""
            if extracted_text and len(extracted_text.strip()) > 30:
                logger.info("Document AI OCR successfully extracted %s chars", len(extracted_text))
                return {
                    "raw_text": extracted_text.strip(),
                    "ocr_engine": "google_document_ai",
                    "confidence": 0.98,
                }
        except Exception as exc:
            logger.warning("Google Document AI processing skipped or failed: %s. Using format fallback...", exc)

        # 2. Format Fallback Extraction
        raw_text = ""
        engine_used = "format_fallback"

        if ext == ".pdf" or mime_type == "application/pdf":
            raw_text = self._extract_pdf(file_bytes)
            engine_used = "pypdf_fallback"
        elif ext in [".docx", ".doc"] or "wordprocessingml" in mime_type or "msword" in mime_type:
            raw_text = self._extract_docx(file_bytes)
            engine_used = "docx_fallback"
        elif ext in [".png", ".jpg", ".jpeg", ".tif", ".tiff"] or "image" in mime_type:
            raw_text = self._extract_image_fallback(file_bytes)
            engine_used = "image_fallback"

        if not raw_text or len(raw_text.strip()) < 10:
            # Final fallback text decoding
            try:
                raw_text = file_bytes.decode("utf-8", errors="ignore")
                engine_used = "raw_text_decoder"
            except Exception:
                raw_text = ""

        if not raw_text or len(raw_text.strip()) == 0:
            raise AppException(
                message="Unable to extract text from the uploaded resume file. The file may be corrupt, unreadable, or password-protected.",
                status_code=400,
            )

        logger.info("Fallback OCR extracted %s chars using %s", len(raw_text), engine_used)
        return {
            "raw_text": raw_text.strip(),
            "ocr_engine": engine_used,
            "confidence": 0.85,
        }

    def _extract_pdf(self, file_bytes: bytes) -> str:
        """Extract text from PDF using pypdf if available, or regex fallback."""
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text_pages = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_pages.append(t)
            return "\n".join(text_pages)
        except Exception as exc:
            logger.warning("pypdf extraction failed: %s. Trying string extraction fallback.", exc)
            # Binary string extraction fallback
            text_content = file_bytes.decode("latin-1", errors="ignore")
            import re
            readable = re.findall(r"[A-Za-z0-9\s.,@+\-(){}:;/]{4,}", text_content)
            return "\n".join(readable)

    def _extract_docx(self, file_bytes: bytes) -> str:
        """Extract text from DOCX using python-docx or zip xml extraction."""
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text]
            for table in doc.tables:
                for row in table.rows:
                    row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        paragraphs.append(row_text)
            return "\n".join(paragraphs)
        except Exception:
            # Fallback zip file XML reading
            try:
                import zipfile
                import xml.etree.ElementTree as ET
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                    xml_content = z.read("word/document.xml")
                    tree = ET.fromstring(xml_content)
                    texts = [node.text for node in tree.iter() if node.text]
                    return " ".join(texts)
            except Exception as exc:
                logger.warning("DOCX zip XML extraction failed: %s", exc)
                return ""

    def _extract_image_fallback(self, file_bytes: bytes) -> str:
        """Fallback image text reader."""
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(io.BytesIO(file_bytes))
            return pytesseract.image_to_string(img)
        except Exception:
            logger.warning("pytesseract/PIL fallback unconfigured.")
            return ""
