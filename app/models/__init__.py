"""SQLAlchemy models — import all so Alembic can auto-detect tables."""

from app.models.otp import OTP
from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.password_reset import PasswordResetToken
from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.company import Company
from app.models.onboarding import CompanySettings, Designation, LeavePolicy, Shift, OnboardingProgress

# Employee module models
from app.models.employee import Employee
from app.models.employee_address import EmployeeAddress
from app.models.employee_document import EmployeeDocument
from app.models.employee_education import EmployeeEducation
from app.models.employee_experience import EmployeeExperience
from app.models.employee_skill import EmployeeSkill
from app.models.asset import Asset, AssetAssignmentHistory, AssetMaintenanceRecord
from app.models.employee_emergency_contact import EmployeeEmergencyContact
from app.models.employee_bank_account import EmployeeBankAccount
from app.models.employee_leave_policy import EmployeeLeavePolicy
from app.models.employee_onboarding import EmployeeOnboarding
from app.models.employee_policy_acceptance import EmployeePolicyAcceptance
from app.models.employee_tax_info import EmployeeTaxInfo
from app.models.hierarchy_audit import HierarchyAuditLog

# Manager module models
from app.models.manager import Manager
from app.models.manager_address import ManagerAddress
from app.models.manager_document import ManagerDocument
from app.models.manager_education import ManagerEducation
from app.models.manager_experience import ManagerExperience
from app.models.manager_skill import ManagerSkill
from app.models.manager_emergency_contact import ManagerEmergencyContact

# Recruitment module models
from app.models.recruitment import (
    Job,
    JobSkill,
    Application,
    ApplicationDocument,
    Interview,
    InterviewRound,
    InterviewSchedule,
    Offer,
    OfferDocument,
    CareerPageSetting,
    Candidate,
    JobRequisition,
    RecruitmentVendor,
    ScorecardTemplate,
    ScorecardSubmission,
    CandidateReferral,
    RecruitmentAutomationRule,
    CandidateCrmNote,
    RecruitmentNotification,
    JobPublishChannel,
)

# Exit module models
from app.models.exit import (
    EmployeeExit,
    KnowledgeTransfer,
    AssetReturn,
    ClearanceRequest,
    ExitInterview,
    FnfSettlement,
    ExitDocument,
)

# Calendar module models
from app.models.calendar import (
    CalendarEvent,
    HolidayCalendar,
    Meeting,
    MeetingParticipant,
    CalendarNotification,
    EventReminder,
)

# Document module models
from app.models.document import (
    DocumentCategory,
    CompanyDocument,
    DocumentTemplate,
    DocumentVersion,
    DocumentSignature,
    DocumentVerification,
    DocumentExpiryTracking,
    DocumentAuditLog,
)
from app.models.document_ocr import DocumentOCRRecord

# Communication module models
from app.models.communication import (
    Announcement,
    AnnouncementRead,
    CompanyNews,
    CompanyEvent,
    EventRegistration,
    Poll,
    PollOption,
    PollVote,
    NotificationCenter,
    CommunicationAuditLog,
)

# AI Hiring Copilot module models
from app.models.ai_copilot import (
    ResumeDocument,
    ResumeExtractedData,
    ResumeEmbedding,
    JobEmbedding,
    CandidateSimilarity,
    CandidateAiAnalysis,
    CandidateRanking,
    InterviewQuestion,
    AiLog,
)

# AI Chat Assistant models
from app.models.ai import AIConversation, AIMessage

# AI Document Analysis models
from app.models.ai_document_analysis import (
    AnalyzedDocument,
    DocumentAnalysisVersion,
    DocumentComparisonRun,
    AnalysisAuditLog,
)

# AI Employee Support models
from app.models.ai_employee_support import (
    SupportTicket,
    TicketUpdate,
)

# AI Interview Bot models
from app.models.ai_interview import (
    AIInterviewSession,
    AIInterviewQuestionInstance,
    AIInterviewResponse,
    AIInterviewScorecard,
)

# HR Analytics AI models
from app.models.hr_analytics import (
    HRAnalyticsSnapshot,
    HRAttritionRiskPrediction,
    HRForecastingRun,
)

# AI Workflow Automation models
from app.models.hr_workflow import (
    HRWorkflowDefinition,
    HRWorkflowInstance,
    HRWorkflowStepInstance,
)

# Performance AI models
from app.models.performance import (
    PerformanceReviewCycle,
    EmployeePerformanceGoal,
    PerformanceReview,
)

# AI Policy Explainer models
from app.models.policy import (
    CompanyPolicyDocument,
    CompanyPolicyChunk,
)

# Employee Mental Wellness AI models
from app.models.wellness import (
    EmployeeWellnessLog,
    WellnessEscalationRule,
    WellnessAnonymousChatSession,
    WellnessAnonymousChatMessage,
)

# AI Productivity Tracking models
from app.models.productivity import (
    EmployeeProductivityLog,
    ProductivityForecastingRun,
)

# AI Goal Generator models
from app.models.generated_goal import (
    GeneratedGoal,
)

# AI Compensation models
from app.models.compensation import (
    MarketCompensationBenchmark,
    AICompensationRecommendation,
)

# AI Behavioural Interview models
from app.models.behavioural_interview import (
    BehaviouralInterviewSession,
    BehaviouralInterviewQuestion,
)

# AI Email Generator models
from app.models.email_generator import (
    GeneratedEmailLog,
)

# AI Emotion Aware Chatbot models
from app.models.emotion_chatbot import (
    EmotionAwareChatSession,
    EmotionAwareChatMessage,
)

# AI Organization Intelligence Map
from app.models.org_map import OrgHierarchySnapshot

# AI Skill Gap Analysis
from app.models.skill_gap import SkillGapAnalysis

# AI Shift Planner
from app.models.shift_plan import ShiftPlan, ShiftPlanEntry

# AI Employee Digital Twin
from app.models.digital_twin import EmployeeDigitalTwin

# AI HR Voice Assistant
from app.models.voice_assistant import VoiceCommandLog

# AI Mood Detection Engine
from app.models.mood_detection import MoodDetectionLog

# AI Career Path Generator
from app.models.career_path import CareerPathPrediction

# AI Learning Recommendation
from app.models.learning_recommendation import LearningRecommendation

# AI Workforce Forecasting
from app.models.workforce_forecast import WorkforceForecastRun

# AI Talent Marketplace
from app.models.talent_marketplace import TalentMatch

# AI Meeting Intelligence
from app.models.meeting_intelligence import MeetingIntelligenceLog

# AI Compliance Monitor
from app.models.compliance_monitor import ComplianceAuditLog

# AI Employee Risk Engine
from app.models.employee_risk import EmployeeRiskAssessment

# AI Executive Copilot
from app.models.executive_copilot import CopilotQueryLog

# AI Recruitment Platform models
from app.models.ai_recruitment import (
    AIResumeDocument,
    CandidateMatchScore,
    AIScreeningResult,
    AIRecruitmentInterviewSession,
    CodingAssessmentRecord,
    HRCopilotQuery,
    JobTemplate,
    RecruitmentAuditLog,
)


# Payroll module models
from app.models.payroll import (
    StatutoryComplianceConfig,
    SalaryStructure,
    PayrollAttendanceInput,
    PayrollRun,
    Payslip,
    EmployeeInvestmentDeclaration,
    PayCycle,
    PayrollAuditLog,
    OvertimePolicy,
    OvertimeEntry,
    BonusPlan,
    BonusAward,
    DeductionComponent,
    AdvanceLoan,
    ReimbursementClaim,
    BankAdviceFile,
    ComplianceObligation,
    ComplianceDocument,
    TaxDeclarationProof,
    BankDisbursementRecord,
)

# Timesheet module models
from app.models.timesheet import Timesheet, TimesheetEntry

# Attendance module models
from app.attendance.models.attendance import Attendance

# Leave module models
from app.models.leave import LeaveRequest

# Travel module models
from app.models.travel import TravelRequest

# Reports module models
from app.models.report import Report

# Connect module models
from app.models.connect import (
    ConnectConversation,
    ConnectConversationParticipant,
    ConnectChannel,
    ConnectChannelMember,
    ConnectMessage,
    ConnectMessageReaction,
    ConnectMessageAttachment,
    ConnectCallLog,
    ConnectMeeting,
    ConnectMeetingParticipant,
    ConnectMeetingMessage,
    ConnectSharedFile,
    ConnectUserPresence,
    ConnectNotification,
    ConnectUserSoundSettings,
)

# Helpdesk module models
from app.models.helpdesk import (
    HelpdeskTicket,
    HelpdeskComment,
    HelpdeskInternalNote,
    HelpdeskAttachment,
    HelpdeskFAQ,
)

__all__ = [
    "HelpdeskTicket",
    "HelpdeskComment",
    "HelpdeskInternalNote",
    "HelpdeskAttachment",
    "HelpdeskFAQ",
    "ConnectConversation",
    "ConnectConversationParticipant",
    "ConnectChannel",
    "ConnectChannelMember",
    "ConnectMessage",
    "ConnectMessageReaction",
    "ConnectMessageAttachment",
    "ConnectCallLog",
    "ConnectMeeting",
    "ConnectMeetingParticipant",
    "ConnectMeetingMessage",
    "ConnectSharedFile",
    "ConnectUserPresence",
    "ConnectNotification",
    "ConnectUserSoundSettings",
    "Company",
    "OTP",
    "User",
    "RefreshToken",
    "Department",
    "Employee",
    "EmployeeAddress",
    "EmployeeDocument",
    "EmployeeEducation",
    "EmployeeExperience",
    "EmployeeSkill",
    "Asset",
    "AssetAssignmentHistory",
    "AssetMaintenanceRecord",
    "EmployeeEmergencyContact",
    "EmployeeBankAccount",
    "EmployeeLeavePolicy",
    "EmployeeOnboarding",
    "EmployeePolicyAcceptance",
    "EmployeeTaxInfo",
    "Manager",
    "ManagerAddress",
    "ManagerDocument",
    "ManagerEducation",
    "ManagerExperience",
    "ManagerSkill",
    "ManagerEmergencyContact",
    "Job",
    "JobSkill",
    "Application",
    "ApplicationDocument",
    "Interview",
    "InterviewRound",
    "InterviewSchedule",
    "Offer",
    "OfferDocument",
    "CareerPageSetting",
    "Candidate",
    "JobRequisition",
    "RecruitmentVendor",
    "ScorecardTemplate",
    "ScorecardSubmission",
    "CandidateReferral",
    "RecruitmentAutomationRule",
    "CandidateCrmNote",
    "RecruitmentNotification",
    "JobPublishChannel",
    "EmployeeExit",
    "KnowledgeTransfer",
    "AssetReturn",
    "ClearanceRequest",
    "ExitInterview",
    "FnfSettlement",
    "ExitDocument",
    "CalendarEvent",
    "HolidayCalendar",
    "Meeting",
    "MeetingParticipant",
    "CalendarNotification",
    "EventReminder",
    "DocumentCategory",
    "EmployeeDocument",
    "CompanyDocument",
    "DocumentTemplate",
    "DocumentVersion",
    "DocumentSignature",
    "DocumentVerification",
    "DocumentExpiryTracking",
    "DocumentAuditLog",
    "Announcement",
    "AnnouncementRead",
    "CompanyNews",
    "CompanyEvent",
    "EventRegistration",
    "Poll",
    "PollOption",
    "PollVote",
    "NotificationCenter",
    "CommunicationAuditLog",
    "ResumeDocument",
    "ResumeExtractedData",
    "ResumeEmbedding",
    "JobEmbedding",
    "CandidateSimilarity",
    "CandidateAiAnalysis",
    "CandidateRanking",
    "InterviewQuestion",
    "AiLog",
    "CompanySettings",
    "Designation",
    "LeavePolicy",
    "Shift",
    "OnboardingProgress",
    "AIConversation",
    "AIMessage",
    "AnalyzedDocument",
    "DocumentAnalysisVersion",
    "DocumentComparisonRun",
    "AnalysisAuditLog",
    "SupportTicket",
    "TicketUpdate",
    "AIInterviewSession",
    "AIInterviewQuestionInstance",
    "AIInterviewResponse",
    "AIInterviewScorecard",
    "HRAnalyticsSnapshot",
    "HRAttritionRiskPrediction",
    "HRForecastingRun",
    "HRWorkflowDefinition",
    "HRWorkflowInstance",
    "HRWorkflowStepInstance",
    "PerformanceReviewCycle",
    "EmployeePerformanceGoal",
    "PerformanceReview",
    "CompanyPolicyDocument",
    "CompanyPolicyChunk",
    "EmployeeWellnessLog",
    "WellnessEscalationRule",
    "WellnessAnonymousChatSession",
    "WellnessAnonymousChatMessage",
    "EmployeeProductivityLog",
    "ProductivityForecastingRun",
    "GeneratedGoal",
    "MarketCompensationBenchmark",
    "AICompensationRecommendation",
    "BehaviouralInterviewSession",
    "BehaviouralInterviewQuestion",
    "GeneratedEmailLog",
    "EmotionAwareChatSession",
    "EmotionAwareChatMessage",
    "OrgHierarchySnapshot",
    "SkillGapAnalysis",
    "ShiftPlan",
    "ShiftPlanEntry",
    "EmployeeDigitalTwin",
    "VoiceCommandLog",
    "MoodDetectionLog",
    "CareerPathPrediction",
    "LearningRecommendation",
    "WorkforceForecastRun",
    "TalentMatch",
    "MeetingIntelligenceLog",
    "ComplianceAuditLog",
    "EmployeeRiskAssessment",
    "CopilotQueryLog",
    "StatutoryComplianceConfig",
    "SalaryStructure",
    "PayrollAttendanceInput",
    "PayrollRun",
    "Payslip",
    "EmployeeInvestmentDeclaration",
    "PayCycle",
    "PayrollAuditLog",
    "OvertimePolicy",
    "OvertimeEntry",
    "BonusPlan",
    "BonusAward",
    "DeductionComponent",
    "AdvanceLoan",
    "ReimbursementClaim",
    "BankAdviceFile",
    "ComplianceObligation",
    "ComplianceDocument",
    "TaxDeclarationProof",
    "BankDisbursementRecord",
    "AIResumeDocument",
    "CandidateMatchScore",
    "AIScreeningResult",
    "AIRecruitmentInterviewSession",
    "CodingAssessmentRecord",
    "HRCopilotQuery",
    "JobTemplate",
    "RecruitmentAuditLog",
    "Timesheet",
    "TimesheetEntry",
    "Attendance",
    "LeaveRequest",
    "TravelRequest",
    "Report",
    "DocumentOCRRecord",
]