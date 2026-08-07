"""FastAPI router for AI Payroll Insights endpoints (/api/v1/ai/payroll/*)."""

from __future__ import annotations

import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.middleware.auth import get_current_user_claims
from app.schemas.auth import APIResponse
from app.schemas.ai_payroll import (
    AnalyzePayrollPayload,
    CostAnalysisResponse,
    CostByDepartmentResponse,
    DetectAnomaliesPayload,
    DetectFraudPayload,
    EmployeePayrollDetailResponse,
    FraudDetectionResponse,
    PayrollAnalyticsResponse,
    PayrollAnomaliesResponse,
    PayrollDashboardResponse,
    PayrollForecastPayload,
    PayrollForecastResponse,
    PayrollHealthScoreResponse,
    SalaryBenchmarkingResponse,
)
from app.services.ai_payroll_service import AIPayrollService

router = APIRouter(prefix="/ai/payroll", tags=["AI Payroll Insights"])


async def get_ai_payroll_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AIPayrollService:
    return AIPayrollService(session=session)


def get_company_id_from_claims(claims: dict) -> Optional[uuid.UUID]:
    co_id_str = claims.get("company_id") if isinstance(claims, dict) else None
    return uuid.UUID(str(co_id_str)) if co_id_str else None


@router.get(
    "/dashboard",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollDashboardResponse],
    summary="Get AI Payroll Insights Dashboard KPIs",
)
async def get_payroll_dashboard(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[PayrollDashboardResponse]:
    """Retrieve dynamic payroll KPIs: Monthly Payroll, Previous Month Payroll, Forecast Next Month, Growth %, Health Score, Employees Paid, Pending Payroll, Status."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_dashboard(company_id=company_id)
    return APIResponse[PayrollDashboardResponse](
        success=True,
        message="Payroll dashboard fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollForecastResponse],
    summary="Get Payroll Forecast",
)
async def get_payroll_forecast(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
    months_ahead: int = Query(12, description="Forecast horizon in months (1-12)"),
) -> APIResponse[PayrollForecastResponse]:
    """Retrieve predictive payroll cost forecast over next 1, 3, 6, or 12 months."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_forecast(company_id=company_id, months_ahead=months_ahead)
    return APIResponse[PayrollForecastResponse](
        success=True,
        message="Payroll forecast fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/cost-analysis",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CostAnalysisResponse],
    summary="Get Payroll Cost Analysis",
)
async def get_payroll_cost_analysis(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[CostAnalysisResponse]:
    """Retrieve overall cost trends, salary distributions, cost drivers, and wage component breakdown."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_cost_analysis(company_id=company_id)
    return APIResponse[CostAnalysisResponse](
        success=True,
        message="Payroll cost analysis fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/cost-by-department",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CostByDepartmentResponse],
    summary="Get Cost By Department",
)
async def get_cost_by_department(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[CostByDepartmentResponse]:
    """Retrieve payroll cost breakdown grouped by department (Total Cost, Avg Salary, Headcount, Overtime, Bonus)."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_cost_by_department(company_id=company_id)
    return APIResponse[CostByDepartmentResponse](
        success=True,
        message="Cost by department fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/benchmarking",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[SalaryBenchmarkingResponse],
    summary="Get Salary Benchmarking Analysis",
)
async def get_salary_benchmarking(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[SalaryBenchmarkingResponse]:
    """Compare employee salaries against internal role averages and market standards."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_benchmarking(company_id=company_id)
    return APIResponse[SalaryBenchmarkingResponse](
        success=True,
        message="Salary benchmarking fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/anomalies",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollAnomaliesResponse],
    summary="Get Payroll Anomaly Detections",
)
async def get_payroll_anomalies(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[PayrollAnomaliesResponse]:
    """Detect unexpected salary spikes, excess overtime, missing deductions, and payroll variance."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_anomalies(company_id=company_id)
    return APIResponse[PayrollAnomaliesResponse](
        success=True,
        message="Payroll anomalies fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/fraud-detection",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[FraudDetectionResponse],
    summary="Get Payroll Fraud Flags",
)
async def get_payroll_fraud_detection(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[FraudDetectionResponse]:
    """Identify ghost employees, duplicate bank account numbers, duplicate PAN/Aadhaar references, and suspicious pay changes."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_fraud_detection(company_id=company_id)
    return APIResponse[FraudDetectionResponse](
        success=True,
        message="Fraud detection flags fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/health-score",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollHealthScoreResponse],
    summary="Get Payroll Health Index",
)
async def get_payroll_health_score(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[PayrollHealthScoreResponse]:
    """Retrieve composite Payroll Health Score (0-100) based on accuracy, processing time, error rate, compliance, and tax precision."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_health_score(company_id=company_id)
    return APIResponse[PayrollHealthScoreResponse](
        success=True,
        message="Payroll health score fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/analytics",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollAnalyticsResponse],
    summary="Get Payroll Analytics Overview",
)
async def get_payroll_analytics(
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[PayrollAnalyticsResponse]:
    """Retrieve overall payroll analytics, monthly trends, and cost distribution percentages."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_analytics(company_id=company_id)
    return APIResponse[PayrollAnalyticsResponse](
        success=True,
        message="Payroll analytics fetched successfully.",
        data=data,
        errors=None,
    )


@router.get(
    "/employee/{employee_id}",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[EmployeePayrollDetailResponse],
    summary="Get Employee Payroll Details",
)
async def get_employee_payroll_detail(
    employee_id: uuid.UUID,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[EmployeePayrollDetailResponse]:
    """Retrieve specific employee payroll compensation breakdown, CTC, monthly gross/net pay, and payslips."""
    data = await service.get_employee_payroll_detail(employee_id=employee_id)
    return APIResponse[EmployeePayrollDetailResponse](
        success=True,
        message="Employee payroll detail fetched successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/forecast",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollForecastResponse],
    summary="Generate AI Payroll Forecast",
)
async def forecast_payroll(
    payload: PayrollForecastPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[PayrollForecastResponse]:
    """Run AI predictive payroll growth model."""
    company_id = get_company_id_from_claims(claims)
    data = await service.get_forecast(company_id=company_id, months_ahead=payload.months_ahead)
    return APIResponse[PayrollForecastResponse](
        success=True,
        message="Payroll forecast generated successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/analyze",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[CostAnalysisResponse],
    summary="Analyze Payroll Run via AI",
)
async def analyze_payroll(
    payload: AnalyzePayrollPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[CostAnalysisResponse]:
    """Trigger AI LLM cost analysis of a specific payroll run."""
    company_id = get_company_id_from_claims(claims)
    data = await service.analyze_payroll(company_id=company_id)
    return APIResponse[CostAnalysisResponse](
        success=True,
        message="Payroll analysis completed successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/detect-anomalies",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[PayrollAnomaliesResponse],
    summary="Detect Payroll Anomalies via AI",
)
async def detect_anomalies(
    payload: DetectAnomaliesPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[PayrollAnomaliesResponse]:
    """Run AI anomaly detection for unexpected salary variations or statutory discrepancies."""
    company_id = get_company_id_from_claims(claims)
    data = await service.detect_anomalies(company_id=company_id)
    return APIResponse[PayrollAnomaliesResponse](
        success=True,
        message="Payroll anomalies detected successfully.",
        data=data,
        errors=None,
    )


@router.post(
    "/detect-fraud",
    status_code=status.HTTP_200_OK,
    response_model=APIResponse[FraudDetectionResponse],
    summary="Detect Payroll Fraud via AI",
)
async def detect_fraud(
    payload: DetectFraudPayload,
    claims: Annotated[dict, Depends(get_current_user_claims)],
    service: Annotated[AIPayrollService, Depends(get_ai_payroll_service)],
) -> APIResponse[FraudDetectionResponse]:
    """Run AI fraud detection scanner for ghost employees, duplicate accounts, and unauthorized pay adjustments."""
    company_id = get_company_id_from_claims(claims)
    data = await service.detect_fraud(company_id=company_id)
    return APIResponse[FraudDetectionResponse](
        success=True,
        message="Payroll fraud detection completed successfully.",
        data=data,
        errors=None,
    )
