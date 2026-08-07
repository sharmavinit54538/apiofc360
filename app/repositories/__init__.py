from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.manager_repository import ManagerRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.recruitment_repository import RecruitmentRepository
from app.repositories.exit_repository import ExitRepository
from app.repositories.calendar_repository import CalendarRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.communication_repository import CommunicationRepository
from app.repositories.ai_copilot_repository import AiCopilotRepository

__all__ = [
    "AuthRepository",
    "UserRepository",
    "EmployeeRepository",
    "ManagerRepository",
    "DepartmentRepository",
    "RecruitmentRepository",
    "ExitRepository",
    "CalendarRepository",
    "DocumentRepository",
    "CommunicationRepository",
    "AiCopilotRepository",
]
