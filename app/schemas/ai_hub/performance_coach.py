"""Schemas for AI Hub Performance Coach module."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class PerformanceCoachOverview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    topPerformersCount: int
    lowPerformersCount: int
    kpiAchievementPct: float
    promotionReadinessPct: float
    criticalSkillGapsCount: int
    activeGoalsCount: int


class GenerateGoalsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    employeeId: str
    role: str
    department: str
    okrCategory: str
    targetHorizon: str


class GeneratedGoalItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    goalId: str
    title: str
    description: str
    targetMetric: str
    currentValue: str = "0"
    dueDate: str
    goalType: str
    scope: str = "INDIVIDUAL"


class GenerateGoalsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    employeeId: str
    role: str
    department: str
    okrCategory: str
    targetHorizon: str
    totalGenerated: int
    goals: list[GeneratedGoalItem] = Field(default_factory=list)


class TrainingRecommendationsRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: str
    skillsGaps: list[str] = Field(default_factory=list)
    level: str = "intermediate"


class CourseRecommendation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    skill: str
    courseTitle: str
    provider: str
    estimatedHours: int
    recommendedForLevel: str
    relevanceScore: float


class TrainingRecommendationsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    department: str
    targetLevel: str
    skillsAnalyzed: list[str] = Field(default_factory=list)
    recommendations: list[CourseRecommendation] = Field(default_factory=list)
    curatedTracks: list[dict[str, Any]] = Field(default_factory=list)
