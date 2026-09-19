"""Small builders so tests read like the situation they describe."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from app.domain.types import (
    ActionExecution,
    ActionKind,
    ActionOutcome,
    AgentStatement,
    Appointment,
    AppointmentStatus,
    CallbackPriority,
    CallbackRequest,
    CallbackStatus,
    CallEvidence,
    CallRecord,
    Disposition,
    Intent,
    Lifecycle,
    StaffAction,
    StaffActionKind,
    StatementKind,
    StatementSource,
    TransferSession,
    TransferStatus,
)

T0 = datetime(2026, 9, 19, 17, 0, tzinfo=UTC)
_ids = itertools.count(1)


def _id(prefix: str) -> str:
    return f"{prefix}-{next(_ids)}"


def call(
    lifecycle: Lifecycle = Lifecycle.ENDED,
    intent: Intent | None = None,
) -> CallRecord:
    return CallRecord(
        id=_id("call"),
        organization_id="org-demo",
        lifecycle=lifecycle,
        agent_classified_intent=intent,
    )


def execution(
    kind: ActionKind,
    outcome: ActionOutcome = ActionOutcome.SUCCEEDED,
    *,
    seconds: int = 0,
    duplicate_of_id: str | None = None,
) -> ActionExecution:
    return ActionExecution(
        id=_id("exec"),
        kind=kind,
        outcome=outcome,
        requested_at=T0 + timedelta(seconds=seconds),
        completed_at=T0 + timedelta(seconds=seconds + 1),
        duplicate_of_id=duplicate_of_id,
    )


def transfer(status: TransferStatus, execution_id: str, reason: str | None = None) -> TransferSession:
    return TransferSession(
        id=_id("transfer"), action_execution_id=execution_id, status=status, failure_reason=reason
    )


def callback(
    status: CallbackStatus = CallbackStatus.CREATED,
    execution_id: str = "exec-x",
    priority: CallbackPriority = CallbackPriority.URGENT,
) -> CallbackRequest:
    return CallbackRequest(
        id=_id("callback"),
        action_execution_id=execution_id,
        status=status,
        priority=priority,
    )


def appointment(
    status: AppointmentStatus = AppointmentStatus.BOOKED, execution_id: str = "exec-x"
) -> Appointment:
    return Appointment(id=_id("appt"), action_execution_id=execution_id, status=status)


def said(kind: StatementKind, sequence_no: int = 0, disposition: Disposition | None = None) -> AgentStatement:
    return AgentStatement(
        id=_id("stmt"),
        kind=kind,
        source=(
            StatementSource.FUNCTION_PARAM
            if kind == StatementKind.REPORTED_DISPOSITION
            else StatementSource.TRANSCRIPT_RULE
        ),
        observed_at=T0 + timedelta(seconds=sequence_no),
        sequence_no=sequence_no,
        disposition=disposition,
    )


def staff(kind: StaffActionKind, target_callback_id: str | None = None) -> StaffAction:
    return StaffAction(
        id=_id("staff"), kind=kind, created_at=T0 + timedelta(minutes=5),
        target_callback_id=target_callback_id, actor="front-desk",
    )


def evidence(call_record: CallRecord | None = None, **kwargs) -> CallEvidence:
    return CallEvidence(
        call=call_record or call(),
        action_executions=tuple(kwargs.get("executions", ())),
        appointments=tuple(kwargs.get("appointments", ())),
        transfer_sessions=tuple(kwargs.get("transfers", ())),
        callback_requests=tuple(kwargs.get("callbacks", ())),
        agent_statements=tuple(kwargs.get("statements", ())),
        staff_actions=tuple(kwargs.get("staff_actions", ())),
    )
