"""Schemas for AI Hub Index (root)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AIHubModuleInfo(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    slug: str
    name: str
    basePath: str
    description: str
    category: str = "AI Services"
    endpointsCount: int


class AIHubIndexResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str = "v1"
    title: str = "AI Hub Gateway"
    description: str = "Unified AI services gateway for apiofc360"
    totalModules: int
    modules: list[AIHubModuleInfo]
