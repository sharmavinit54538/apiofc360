"""Core modules services aggregator."""

from app.services.core_modules.attendance_service import AttendanceCoreService
from app.services.core_modules.analytics_service import AnalyticsService
from app.services.core_modules.settings_service import SettingsService
from app.services.core_modules.performance_service import PerformanceCoreService
from app.services.core_modules.users_profile_service import UsersProfileService
from app.services.core_modules.department_service import DepartmentCoreService
from app.services.core_modules.compliance_health_service import ComplianceService, EmployeeHealthService
from app.services.core_modules.ai_assistants_service import AIAssistantsCoreService
from app.services.core_modules.misc_service import (
    RecruiterCoreService,
    WorkforceInsightsService,
    ManagersService,
    ReportsCoreService,
    TopLevelMiscService,
)

__all__ = [
    "AttendanceCoreService",
    "AnalyticsService",
    "SettingsService",
    "PerformanceCoreService",
    "UsersProfileService",
    "DepartmentCoreService",
    "ComplianceService",
    "EmployeeHealthService",
    "AIAssistantsCoreService",
    "RecruiterCoreService",
    "WorkforceInsightsService",
    "ManagersService",
    "ReportsCoreService",
    "TopLevelMiscService",
]
