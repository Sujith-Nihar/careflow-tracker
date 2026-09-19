"""Domain vocabulary for the evidence model.

Every name here matches the terminology fixed in CLAUDE.md and docs/DATA_MODEL.md.
These types carry evidence only. Nothing in this module knows about HTTP, the
database, Vogent, or the evaluation harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Lifecycle(StrEnum):
    """Where a call is in its own life, independent of what was accomplished."""

    REGISTERED = "registered"
    IN_PROGRESS = "in_progress"
    ENDED = "ended"
    ENDED_UNCONFIRMED = "ended_unconfirmed"


class ActionKind(StrEnum):
    SCHEDULE_APPOINTMENT = "schedule_appointment"
    TRANSFER_TRIAGE = "transfer_triage"
    CREATE_CALLBACK = "create_callback"
    REPORT_DISPOSITION = "report_disposition"


#: The kinds that actually change the world. `report_disposition` is the agent's
#: own claim about the call and is deliberately excluded: a claim is not an action.
ACTION_KINDS: frozenset[ActionKind] = frozenset(
    {ActionKind.SCHEDULE_APPOINTMENT, ActionKind.TRANSFER_TRIAGE, ActionKind.CREATE_CALLBACK}
)


class ActionOutcome(StrEnum):
    REQUESTED = "requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"
    #: The action was correctly not performed: asking for a fallback after a
    #: transfer that actually connected. Not a success and not a failure.
    NOT_APPLICABLE = "not_applicable"


class TransferStatus(StrEnum):
    CONNECTED = "connected"
    FAILED = "failed"
    UNVERIFIED = "unverified"


class CallbackStatus(StrEnum):
    CREATED = "created"
    COMPLETED = "completed"


class CallbackPriority(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class Intent(StrEnum):
    ROUTINE_SCHEDULING = "routine_scheduling"
    POST_OPERATIVE_CONCERN = "post_operative_concern"
    OTHER = "other"


class StatementKind(StrEnum):
    """What the agent told the caller. Evidence of speech, never of action."""

    PROMISED_TRANSFER = "promised_transfer"
    PROMISED_CALLBACK = "promised_callback"
    PROMISED_APPOINTMENT = "promised_appointment"
    DISCLOSED_TRANSFER_FAILED = "disclosed_transfer_failed"
    DISCLOSED_CALLBACK_FAILED = "disclosed_callback_failed"
    DISCLOSED_SCHEDULING_FAILED = "disclosed_scheduling_failed"
    REPORTED_DISPOSITION = "reported_disposition"


class StatementSource(StrEnum):
    TRANSCRIPT_RULE = "transcript_rule"
    FUNCTION_PARAM = "function_param"


class Disposition(StrEnum):
    """The agent's structured claim, submitted through `report_disposition`."""

    SCHEDULED = "scheduled"
    TRANSFERRED = "transferred"
    CALLBACK_PENDING = "callback_pending"
    ESCALATION_FAILED = "escalation_failed"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


#: Dispositions that assert the caller's need was met. Contrasting these with the
#: derived status is what exposes the customer's reported bug.
COMPLETION_CLAIMS: frozenset[Disposition] = frozenset(
    {Disposition.SCHEDULED, Disposition.TRANSFERRED, Disposition.RESOLVED}
)


class StaffActionKind(StrEnum):
    CALLBACK_COMPLETED = "callback_completed"
    REVIEWED = "reviewed"


class CallStatus(StrEnum):
    """Staff-visible operational truth. Derived, never stored as an input."""

    IN_PROGRESS = "in_progress"
    COMPLETED_SCHEDULED = "completed_scheduled"
    COMPLETED_TRANSFERRED = "completed_transferred"
    CLOSED_BY_STAFF = "closed_by_staff"
    CALLBACK_PENDING = "callback_pending"
    SCHEDULING_INCOMPLETE = "scheduling_incomplete"
    CALLBACK_FAILED = "callback_failed"
    ROUTING_GAP = "routing_gap"
    ESCALATION_FAILED = "escalation_failed"
    NO_ACTION_RECORDED = "no_action_recorded"
    NEEDS_REVIEW = "needs_review"


class Severity(int):
    """0 nothing to do · 1 routine · 2 urgent · 3 high · 4 critical."""

    NONE = 0
    ROUTINE = 1
    URGENT = 2
    HIGH = 3
    CRITICAL = 4


@dataclass(frozen=True, slots=True)
class CallRecord:
    id: str
    organization_id: str
    lifecycle: Lifecycle
    #: How the agent itself categorised the call (from `report_disposition`).
    #: A classification is a claim; it may be wrong, and derivation treats it as
    #: a reason to demand evidence, never as evidence.
    agent_classified_intent: Intent | None = None


@dataclass(frozen=True, slots=True)
class ActionExecution:
    id: str
    kind: ActionKind
    outcome: ActionOutcome
    requested_at: datetime
    completed_at: datetime | None = None
    downstream_ref: str | None = None
    duplicate_of_id: str | None = None

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of_id is not None


@dataclass(frozen=True, slots=True)
class Appointment:
    id: str
    action_execution_id: str
    status: AppointmentStatus


@dataclass(frozen=True, slots=True)
class TransferSession:
    id: str
    action_execution_id: str
    status: TransferStatus
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CallbackRequest:
    """A row exists only when the callback queue accepted the request.

    A failed creation deliberately leaves no row: the failure lives on the
    action execution. This is what separates "fallback attempted" from
    "fallback actually created".
    """

    id: str
    action_execution_id: str
    status: CallbackStatus
    priority: CallbackPriority


@dataclass(frozen=True, slots=True)
class AgentStatement:
    id: str
    kind: StatementKind
    source: StatementSource
    observed_at: datetime
    sequence_no: int = 0
    disposition: Disposition | None = None
    evidence_text: str | None = None


@dataclass(frozen=True, slots=True)
class StaffAction:
    id: str
    kind: StaffActionKind
    created_at: datetime
    target_callback_id: str | None = None
    actor: str | None = None


@dataclass(frozen=True, slots=True)
class CallEvidence:
    """Everything derivation is allowed to see for one call.

    Note what is absent: transcript text and evaluation scenario truth. Derivation
    must behave identically in production, where neither exists.
    """

    call: CallRecord
    action_executions: tuple[ActionExecution, ...] = ()
    appointments: tuple[Appointment, ...] = ()
    transfer_sessions: tuple[TransferSession, ...] = ()
    callback_requests: tuple[CallbackRequest, ...] = ()
    agent_statements: tuple[AgentStatement, ...] = ()
    staff_actions: tuple[StaffAction, ...] = ()


@dataclass(frozen=True, slots=True)
class DerivedStatus:
    status: CallStatus
    severity: int
    requires_staff_action: bool
    reason: str
    next_step: str
    promise_mismatch: bool = False
    mismatch_details: tuple[str, ...] = ()
    evidence_refs: dict[str, str] = field(default_factory=dict)
