"""Unified ResponseParser aggregator class."""

from __future__ import annotations

from app.llm.response_parser.extraction import JSONExtractionMixin
from app.llm.response_parser.fields import FieldExtractionMixin
from app.llm.response_parser.security import SecurityMixin
from app.llm.response_parser.validation import ValidationMixin


class ResponseParser(
    JSONExtractionMixin,
    FieldExtractionMixin,
    SecurityMixin,
    ValidationMixin,
):
    """Facade class wrapping LLM response parsing functions."""
    pass
