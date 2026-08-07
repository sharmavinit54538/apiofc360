"""Parser Service for extracting structured JSON representations from Google Document AI output."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ParserService:
    """Parses Google Document AI output protobuf objects or dictionaries into clean JSON data."""

    def parse_document(self, document_obj: Any) -> dict[str, Any]:
        """Convert documentai.Document object or dict into structured response dictionary."""
        # If input is structured dictionary, parse directly
        if isinstance(document_obj, dict):
            return self._parse_dict(document_obj)

        text = getattr(document_obj, "text", "") or ""
        pages_proto = getattr(document_obj, "pages", []) or []
        entities_proto = getattr(document_obj, "entities", []) or []

        page_count = len(pages_proto)
        extracted_entities = self._extract_entities(entities_proto)
        extracted_tables = self._extract_tables(pages_proto, text)
        extracted_form_fields = self._extract_form_fields(pages_proto, text)
        extracted_pages = self._extract_pages_summary(pages_proto)

        # Compute overall confidence
        confidence = self._calculate_overall_confidence(
            extracted_entities, extracted_form_fields, pages_proto
        )

        # Build raw dict representation
        raw_dict = {}
        try:
            from google.cloud import documentai_v1 as documentai
            raw_dict = type(document_obj).to_dict(document_obj)
        except Exception as exc:
            logger.debug("Failed to serialize document object with to_dict(): %s", exc)
            raw_dict = {
                "text": text[:1000],
                "page_count": page_count,
                "entity_count": len(extracted_entities),
            }

        return {
            "text": text,
            "page_count": page_count,
            "confidence": round(confidence, 4),
            "entities": extracted_entities,
            "tables": extracted_tables,
            "form_fields": extracted_form_fields,
            "pages": extracted_pages,
            "raw_response": raw_dict,
        }

    def _extract_text_from_anchor(self, text_anchor: Any, full_text: str) -> str:
        """Extract substring from full document text using text anchor segments."""
        if not text_anchor or not full_text:
            return ""
        text_segments = []
        text_segments_proto = getattr(text_anchor, "text_segments", []) or []
        for segment in text_segments_proto:
            start_index = int(getattr(segment, "start_index", 0) or 0)
            end_index = int(getattr(segment, "end_index", 0) or 0)
            if end_index > start_index and start_index < len(full_text):
                text_segments.append(full_text[start_index:end_index])
        return "".join(text_segments).strip()

    def _extract_entities(self, entities_proto: Any) -> list[dict[str, Any]]:
        """Extract structured entity list."""
        entities = []
        for entity in entities_proto:
            entity_type = getattr(entity, "type_", None) or getattr(entity, "type", "entity")
            mention_text = getattr(entity, "mention_text", "") or ""
            confidence = float(getattr(entity, "confidence", 0.0) or 0.0)

            normalized_val = None
            if hasattr(entity, "normalized_value") and entity.normalized_value:
                norm = entity.normalized_value
                normalized_val = getattr(norm, "text", None) or getattr(norm, "structured_value", None)

            entities.append({
                "type": entity_type,
                "mention_text": mention_text,
                "confidence": round(confidence, 4),
                "normalized_value": normalized_val,
            })
        return entities

    def _extract_tables(self, pages_proto: Any, full_text: str) -> list[dict[str, Any]]:
        """Extract tables from pages."""
        tables = []
        for p_idx, page in enumerate(pages_proto, start=1):
            page_tables = getattr(page, "tables", []) or []
            for table in page_tables:
                header_rows = []
                body_rows = []

                header_rows_proto = getattr(table, "header_rows", []) or []
                for row in header_rows_proto:
                    row_cells = []
                    for cell in getattr(row, "cells", []) or []:
                        cell_text = self._extract_text_from_anchor(getattr(cell, "layout", None) and cell.layout.text_anchor, full_text)
                        row_cells.append(cell_text)
                    if row_cells:
                        header_rows.append(row_cells)

                body_rows_proto = getattr(table, "body_rows", []) or []
                for row in body_rows_proto:
                    row_cells = []
                    for cell in getattr(row, "cells", []) or []:
                        cell_text = self._extract_text_from_anchor(getattr(cell, "layout", None) and cell.layout.text_anchor, full_text)
                        row_cells.append(cell_text)
                    if row_cells:
                        body_rows.append(row_cells)

                layout = getattr(table, "layout", None)
                table_confidence = float(getattr(layout, "confidence", 0.90) or 0.90) if layout else 0.90

                tables.append({
                    "page_number": p_idx,
                    "header_rows": header_rows,
                    "rows": body_rows,
                    "confidence": round(table_confidence, 4),
                })
        return tables

    def _extract_form_fields(self, pages_proto: Any, full_text: str) -> list[dict[str, Any]]:
        """Extract key-value form fields from pages."""
        fields = []
        for page in pages_proto:
            form_fields_proto = getattr(page, "form_fields", []) or []
            for field in form_fields_proto:
                field_name_obj = getattr(field, "field_name", None)
                field_value_obj = getattr(field, "field_value", None)

                name_text = ""
                name_conf = 0.0
                if field_name_obj:
                    name_text = self._extract_text_from_anchor(getattr(field_name_obj, "text_anchor", None), full_text)
                    name_conf = float(getattr(field_name_obj, "confidence", 0.0) or 0.0)

                value_text = ""
                value_conf = 0.0
                if field_value_obj:
                    value_text = self._extract_text_from_anchor(getattr(field_value_obj, "text_anchor", None), full_text)
                    value_conf = float(getattr(field_value_obj, "confidence", 0.0) or 0.0)

                fields.append({
                    "field_name": name_text,
                    "field_value": value_text,
                    "name_confidence": round(name_conf, 4),
                    "value_confidence": round(value_conf, 4),
                })
        return fields

    def _extract_pages_summary(self, pages_proto: Any) -> list[dict[str, Any]]:
        """Extract per-page summary."""
        page_summaries = []
        for p_idx, page in enumerate(pages_proto, start=1):
            page_num = int(getattr(page, "page_number", p_idx) or p_idx)

            dim = getattr(page, "dimension", None)
            width = float(getattr(dim, "width", 0.0) or 0.0) if dim else 0.0
            height = float(getattr(dim, "height", 0.0) or 0.0) if dim else 0.0
            unit = str(getattr(dim, "unit", "pt") or "pt") if dim else "pt"

            paragraphs_count = len(getattr(page, "paragraphs", []) or [])
            lines_count = len(getattr(page, "lines", []) or [])
            tokens_count = len(getattr(page, "tokens", []) or [])

            page_summaries.append({
                "page_number": page_num,
                "width": width,
                "height": height,
                "unit": unit,
                "paragraphs_count": paragraphs_count,
                "lines_count": lines_count,
                "tokens_count": tokens_count,
            })
        return page_summaries

    def _calculate_overall_confidence(
        self,
        entities: list[dict],
        form_fields: list[dict],
        pages_proto: Any,
    ) -> float:
        """Calculate weighted average confidence score for the processed document."""
        scores = []
        for ent in entities:
            if ent.get("confidence"):
                scores.append(ent["confidence"])
        for ff in form_fields:
            if ff.get("value_confidence"):
                scores.append(ff["value_confidence"])

        for page in pages_proto:
            tokens = getattr(page, "tokens", []) or []
            for token in tokens:
                layout = getattr(token, "layout", None)
                if layout and hasattr(layout, "confidence"):
                    conf = float(getattr(layout, "confidence", 0.0) or 0.0)
                    if conf > 0:
                        scores.append(conf)

        if not scores:
            return 0.95  # Default confidence if no granular token scores present

        return sum(scores) / len(scores)

    def _parse_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Fallback method when a plain dictionary is passed."""
        return {
            "text": data.get("text", ""),
            "page_count": data.get("page_count", 1),
            "confidence": data.get("confidence", 0.95),
            "entities": data.get("entities", []),
            "tables": data.get("tables", []),
            "form_fields": data.get("form_fields", []),
            "pages": data.get("pages", []),
            "raw_response": data,
        }
