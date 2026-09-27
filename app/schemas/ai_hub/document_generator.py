"""Schemas for AI Hub Document Generator module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class DocumentGeneratorOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalTemplates: int
    totalGeneratedDocuments: int
    supportedFormats: list[str] = Field(default_factory=lambda: ["pdf", "docx", "html", "txt"])
    recentGenerated: list[dict[str, Any]] = Field(default_factory=list)


class DocumentTemplateItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    templateId: str
    name: str
    description: Optional[str] = None
    placeholders: list[str] = Field(default_factory=list)
    createdAt: str


class DocumentTemplatesList(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total: int
    templates: list[DocumentTemplateItem] = Field(default_factory=list)


class GenerateDocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    templateId: str
    title: str
    variables: dict[str, Any] = Field(default_factory=dict)
    format: str = "pdf"


class GenerateDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    documentId: str
    templateId: str
    title: str
    format: str
    filePathOrUrl: str
    variablesApplied: dict[str, Any] = Field(default_factory=dict)
    generatedAt: str


class PreviewDocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    templateId: str
    variables: dict[str, Any] = Field(default_factory=dict)


class PreviewDocumentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    templateId: str
    templateName: str
    renderedContent: str
    missingPlaceholders: list[str] = Field(default_factory=list)
    variablesUsed: dict[str, Any] = Field(default_factory=dict)
