"""Reports Service handling business logic, transformations, and security for OFC360 Reports APIs."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.reports_repository import ReportsRepository
from app.schemas.reports import (
    CultureBreakdownItem,
    CultureDistributionItem,
    CultureFeedbackData,
    CultureFeedbackTheme,
    CultureTelemetryData,
    CultureTrendItem,
    EngagementBreakdownItem,
    EngagementSummaryData,
    EngagementSurveyItem,
    EngagementSurveyListResponse,
    EngagementTrendItem,
    EnpsTrendItem,
)

logger = logging.getLogger(__name__)


class ReportsService:
    """Service providing business logic for Engagement and Culture report endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ReportsRepository(session)

    # ==============================================================================
    # 1. ENGAGEMENT REPORTS
    # ==============================================================================

    async def get_engagement_summary(
        self, company_id: uuid.UUID
    ) -> EngagementSummaryData:
        """Retrieve aggregated engagement metrics for company."""
        data = await self.repo.get_engagement_summary(company_id=company_id)
        return EngagementSummaryData(**data)

    async def get_engagement_trends(
        self, company_id: uuid.UUID, period: str = "6m"
    ) -> List[EngagementTrendItem]:
        """Retrieve historical engagement trend items."""
        items = await self.repo.get_engagement_trends(company_id=company_id, period_str=period)
        return [EngagementTrendItem(**item) for item in items]

    async def get_enps_trends(
        self, company_id: uuid.UUID, period: str = "6m"
    ) -> List[EnpsTrendItem]:
        """Retrieve historical eNPS trend items."""
        items = await self.repo.get_enps_trends(company_id=company_id, period_str=period)
        return [EnpsTrendItem(**item) for item in items]

    async def get_engagement_breakdown(
        self, company_id: uuid.UUID
    ) -> List[EngagementBreakdownItem]:
        """Retrieve engagement breakdown by department."""
        items = await self.repo.get_engagement_breakdown(company_id=company_id)
        return [EngagementBreakdownItem(**item) for item in items]

    async def get_engagement_surveys(
        self,
        company_id: uuid.UUID,
        page: int = 1,
        limit: int = 10,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> EngagementSurveyListResponse:
        """Retrieve paginated engagement surveys list."""
        items_raw, total = await self.repo.get_engagement_surveys(
            company_id=company_id,
            page=page,
            limit=limit,
            status_filter=status_filter,
            search=search,
        )
        return EngagementSurveyListResponse(
            items=[EngagementSurveyItem(**item) for item in items_raw],
            total=total,
            page=page,
            limit=limit,
        )

    # ==============================================================================
    # 2. CULTURE REPORTS
    # ==============================================================================

    async def get_culture_telemetry(
        self, company_id: uuid.UUID
    ) -> CultureTelemetryData:
        """Retrieve organizational culture telemetry and D&I metrics."""
        data = await self.repo.get_culture_telemetry(company_id=company_id)
        return CultureTelemetryData(**data)

    async def get_culture_trends(
        self, company_id: uuid.UUID, period: str = "6m"
    ) -> List[CultureTrendItem]:
        """Retrieve historical culture score trends."""
        items = await self.repo.get_culture_trends(company_id=company_id, period_str=period)
        return [CultureTrendItem(**item) for item in items]

    async def get_culture_breakdown(
        self, company_id: uuid.UUID
    ) -> List[CultureBreakdownItem]:
        """Retrieve culture breakdown by department."""
        items = await self.repo.get_culture_breakdown(company_id=company_id)
        return [CultureBreakdownItem(**item) for item in items]

    async def get_culture_feedback(
        self, company_id: uuid.UUID
    ) -> CultureFeedbackData:
        """Retrieve aggregated employee feedback analysis."""
        data = await self.repo.get_culture_feedback(company_id=company_id)
        return CultureFeedbackData(**data)
