"""Centralized Exit State Machine - Canonical statuses and transitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet


class ExitStatus(str, Enum):
    """Canonical exit statuses."""
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_MANAGER_APPROVAL = "PENDING_MANAGER_APPROVAL"
    MANAGER_APPROVED = "MANAGER_APPROVED"
    MANAGER_REJECTED = "MANAGER_REJECTED"
    PENDING_HR_APPROVAL = "PENDING_HR_APPROVAL"
    HR_APPROVED = "HR_APPROVED"
    HR_REJECTED = "HR_REJECTED"
    NOTICE_PERIOD = "NOTICE_PERIOD"
    KNOWLEDGE_TRANSFER_PENDING = "KNOWLEDGE_TRANSFER_PENDING"
    ASSET_RETURN_PENDING = "ASSET_RETURN_PENDING"
    NO_DUES_PENDING = "NO_DUES_PENDING"
    EXIT_INTERVIEW_PENDING = "EXIT_INTERVIEW_PENDING"
    FNF_PENDING = "FNF_PENDING"
    FNF_FINALIZED = "FNF_FINALIZED"
    SETTLED = "SETTLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# Terminal statuses that cannot be transitioned from
TERMINAL_STATUSES: FrozenSet[ExitStatus] = frozenset({
    ExitStatus.COMPLETED,
    ExitStatus.CANCELLED,
    ExitStatus.MANAGER_REJECTED,
    ExitStatus.HR_REJECTED,
})

# Statuses that represent an "active" exit (not terminal)
ACTIVE_STATUSES: FrozenSet[ExitStatus] = frozenset({
    ExitStatus.DRAFT,
    ExitStatus.SUBMITTED,
    ExitStatus.PENDING_MANAGER_APPROVAL,
    ExitStatus.MANAGER_APPROVED,
    ExitStatus.PENDING_HR_APPROVAL,
    ExitStatus.HR_APPROVED,
    ExitStatus.NOTICE_PERIOD,
    ExitStatus.KNOWLEDGE_TRANSFER_PENDING,
    ExitStatus.ASSET_RETURN_PENDING,
    ExitStatus.NO_DUES_PENDING,
    ExitStatus.EXIT_INTERVIEW_PENDING,
    ExitStatus.FNF_PENDING,
    ExitStatus.FNF_FINALIZED,
    ExitStatus.SETTLED,
})


# Allowed transitions: from_status -> set of allowed to_statuses
ALLOWED_TRANSITIONS: dict[ExitStatus, FrozenSet[ExitStatus]] = {
    ExitStatus.DRAFT: frozenset({ExitStatus.SUBMITTED, ExitStatus.CANCELLED}),
    ExitStatus.SUBMITTED: frozenset({ExitStatus.PENDING_MANAGER_APPROVAL, ExitStatus.PENDING_HR_APPROVAL, ExitStatus.CANCELLED}),
    ExitStatus.PENDING_MANAGER_APPROVAL: frozenset({ExitStatus.MANAGER_APPROVED, ExitStatus.MANAGER_REJECTED, ExitStatus.CANCELLED}),
    ExitStatus.MANAGER_APPROVED: frozenset({ExitStatus.PENDING_HR_APPROVAL, ExitStatus.CANCELLED}),
    ExitStatus.MANAGER_REJECTED: frozenset({ExitStatus.SUBMITTED}),  # Allow re-application
    ExitStatus.PENDING_HR_APPROVAL: frozenset({ExitStatus.HR_APPROVED, ExitStatus.HR_REJECTED, ExitStatus.CANCELLED}),
    ExitStatus.HR_APPROVED: frozenset({ExitStatus.NOTICE_PERIOD, ExitStatus.CANCELLED}),
    ExitStatus.HR_REJECTED: frozenset({ExitStatus.SUBMITTED}),  # Allow re-application
    ExitStatus.NOTICE_PERIOD: frozenset({ExitStatus.KNOWLEDGE_TRANSFER_PENDING, ExitStatus.CANCELLED}),
    ExitStatus.KNOWLEDGE_TRANSFER_PENDING: frozenset({ExitStatus.ASSET_RETURN_PENDING, ExitStatus.CANCELLED}),
    ExitStatus.ASSET_RETURN_PENDING: frozenset({ExitStatus.NO_DUES_PENDING, ExitStatus.CANCELLED}),
    ExitStatus.NO_DUES_PENDING: frozenset({ExitStatus.EXIT_INTERVIEW_PENDING, ExitStatus.CANCELLED}),
    ExitStatus.EXIT_INTERVIEW_PENDING: frozenset({ExitStatus.FNF_PENDING, ExitStatus.CANCELLED}),
    ExitStatus.FNF_PENDING: frozenset({ExitStatus.FNF_FINALIZED, ExitStatus.CANCELLED}),
    ExitStatus.FNF_FINALIZED: frozenset({ExitStatus.SETTLED, ExitStatus.CANCELLED}),
    ExitStatus.SETTLED: frozenset({ExitStatus.COMPLETED, ExitStatus.CANCELLED}),
    ExitStatus.COMPLETED: frozenset(),  # Terminal
    ExitStatus.CANCELLED: frozenset(),  # Terminal
}


@dataclass(frozen=True)
class TransitionResult:
    """Result of a state transition validation."""
    allowed: bool
    from_status: ExitStatus
    to_status: ExitStatus
    reason: str | None = None


def validate_transition(from_status: str, to_status: str) -> TransitionResult:
    """Validate if a status transition is allowed.
    
    Args:
        from_status: Current status
        to_status: Target status
        
    Returns:
        TransitionResult with validation outcome
    """
    try:
        from_enum = ExitStatus(from_status.upper())
        to_enum = ExitStatus(to_status.upper())
    except ValueError as e:
        return TransitionResult(
            allowed=False,
            from_status=ExitStatus(from_status.upper()) if from_status.upper() in ExitStatus.__members__ else ExitStatus.DRAFT,
            to_status=ExitStatus(to_status.upper()) if to_status.upper() in ExitStatus.__members__ else ExitStatus.DRAFT,
            reason=f"Invalid status value: {e}"
        )
    
    # Terminal states cannot transition out (except explicit re-application from rejection)
    if from_enum in TERMINAL_STATUSES:
        # Allow re-application from rejection states
        if from_enum in {ExitStatus.MANAGER_REJECTED, ExitStatus.HR_REJECTED} and to_enum == ExitStatus.SUBMITTED:
            return TransitionResult(allowed=True, from_status=from_enum, to_status=to_enum)
        return TransitionResult(
            allowed=False,
            from_status=from_enum,
            to_status=to_enum,
            reason=f"Cannot transition from terminal status '{from_enum.value}'"
        )
    
    allowed_targets = ALLOWED_TRANSITIONS.get(from_enum, frozenset())
    if to_enum not in allowed_targets:
        return TransitionResult(
            allowed=False,
            from_status=from_enum,
            to_status=to_enum,
            reason=f"Invalid transition from '{from_enum.value}' to '{to_enum.value}'. Allowed: {[s.value for s in allowed_targets]}"
        )
    
    return TransitionResult(allowed=True, from_status=from_enum, to_status=to_enum)


def get_allowed_transitions(from_status: str) -> list[str]:
    """Get list of allowed next statuses from current status."""
    try:
        from_enum = ExitStatus(from_status.upper())
    except ValueError:
        return []
    
    if from_enum in TERMINAL_STATUSES:
        if from_enum in {ExitStatus.MANAGER_REJECTED, ExitStatus.HR_REJECTED}:
            return [ExitStatus.SUBMITTED.value]
        return []
    
    return [s.value for s in ALLOWED_TRANSITIONS.get(from_enum, frozenset())]


def is_terminal(status: str) -> bool:
    """Check if a status is terminal."""
    try:
        return ExitStatus(status.upper()) in TERMINAL_STATUSES
    except ValueError:
        return False


def is_active(status: str) -> bool:
    """Check if a status represents an active (non-terminal) exit."""
    try:
        return ExitStatus(status.upper()) in ACTIVE_STATUSES
    except ValueError:
        return False


def get_status_display_name(status: str) -> str:
    """Get human-readable display name for a status."""
    display_names = {
        ExitStatus.DRAFT: "Draft",
        ExitStatus.SUBMITTED: "Submitted",
        ExitStatus.PENDING_MANAGER_APPROVAL: "Pending Manager Approval",
        ExitStatus.MANAGER_APPROVED: "Manager Approved",
        ExitStatus.MANAGER_REJECTED: "Manager Rejected",
        ExitStatus.PENDING_HR_APPROVAL: "Pending HR Approval",
        ExitStatus.HR_APPROVED: "HR Approved",
        ExitStatus.HR_REJECTED: "HR Rejected",
        ExitStatus.NOTICE_PERIOD: "Notice Period",
        ExitStatus.KNOWLEDGE_TRANSFER_PENDING: "Knowledge Transfer Pending",
        ExitStatus.ASSET_RETURN_PENDING: "Asset Return Pending",
        ExitStatus.NO_DUES_PENDING: "No Dues Pending",
        ExitStatus.EXIT_INTERVIEW_PENDING: "Exit Interview Pending",
        ExitStatus.FNF_PENDING: "F&F Pending",
        ExitStatus.FNF_FINALIZED: "F&F Finalized",
        ExitStatus.SETTLED: "Settled",
        ExitStatus.COMPLETED: "Completed",
        ExitStatus.CANCELLED: "Cancelled",
    }
    try:
        return display_names[ExitStatus(status.upper())]
    except ValueError:
        return status


# Legacy status mapping for backward compatibility
LEGACY_STATUS_MAP = {
    "PENDING": ExitStatus.SUBMITTED,
    "APPROVED": ExitStatus.HR_APPROVED,
    "REJECTED": ExitStatus.HR_REJECTED,
    "IN_PROGRESS": ExitStatus.NOTICE_PERIOD,
    "PENDING_CLEARANCE": ExitStatus.NO_DUES_PENDING,
}

def normalize_legacy_status(status: str) -> ExitStatus:
    """Normalize legacy status values to canonical ones."""
    upper = status.upper()
    if upper in ExitStatus.__members__:
        return ExitStatus(upper)
    return LEGACY_STATUS_MAP.get(upper, ExitStatus.SUBMITTED)


__all__ = [
    "ExitStatus",
    "TERMINAL_STATUSES",
    "ACTIVE_STATUSES",
    "ALLOWED_TRANSITIONS",
    "TransitionResult",
    "validate_transition",
    "get_allowed_transitions",
    "is_terminal",
    "is_active",
    "get_status_display_name",
    "normalize_legacy_status",
]