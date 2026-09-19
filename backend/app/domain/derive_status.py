"""Deterministic derivation of the staff-visible status of a call.

This is the module the whole project exists to make trustworthy. It is pure: it
takes persisted evidence and returns a decision, with no I/O and no randomness.

Two rules hold everywhere below.

1. A promise is not evidence. Nothing the agent said can move a call into a
   `completed_*` status. Completion requires a downstream record in a success
   state, produced by an action execution the backend actually handled.
2. Absence of evidence is not completion. A call that ended with nothing
   recorded needs a human, it is not "fine".

Rules are evaluated in the order below and the first match wins. Post-operative
handling outranks scheduling because a caller with a surgical concern who was
given an appointment instead of a transfer is a policy failure, not a success.
"""

from __future__ import annotations

from .types import (
    ACTION_KINDS,
    COMPLETION_CLAIMS,
    ActionExecution,
    ActionKind,
    ActionOutcome,
    AppointmentStatus,
    CallbackPriority,
    CallbackStatus,
    CallEvidence,
    CallStatus,
    DerivedStatus,
    Intent,
    Lifecycle,
    Severity,
    StaffActionKind,
    StatementKind,
    TransferStatus,
)

OPEN_LIFECYCLES = frozenset({Lifecycle.REGISTERED, Lifecycle.IN_PROGRESS})


def _primary(executions: tuple[ActionExecution, ...]) -> list[ActionExecution]:
    """Executions that represent distinct attempts (duplicates collapse onto their original)."""
    return [e for e in executions if not e.is_duplicate]


def _attempted(executions: list[ActionExecution], kind: ActionKind) -> list[ActionExecution]:
    """Executions that represent a real attempt at this action.

    `not_applicable` is excluded: it records that the backend was asked for an
    action and correctly declined to take one, which is not an attempt.
    """
    return [
        e for e in executions if e.kind == kind and e.outcome is not ActionOutcome.NOT_APPLICABLE
    ]


def derive_status(evidence: CallEvidence) -> DerivedStatus:
    """Return the staff-visible status for one call, with its justification."""
    executions = _primary(evidence.action_executions)
    refs: dict[str, str] = {}

    # ---- 1. The call has not finished yet. ------------------------------------
    if evidence.call.lifecycle in OPEN_LIFECYCLES:
        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.IN_PROGRESS,
                severity=Severity.NONE,
                requires_staff_action=False,
                reason="The call is still in progress.",
                next_step="Wait for the call to end.",
                evidence_refs=refs,
            ),
            suppress_mismatch=True,
        )

    # ---- 2. A staff member already closed the loop. ---------------------------
    completed_callbacks = {
        c.id for c in evidence.callback_requests if c.status == CallbackStatus.COMPLETED
    }
    closure = next(
        (
            s
            for s in evidence.staff_actions
            if s.kind == StaffActionKind.CALLBACK_COMPLETED
            and (s.target_callback_id in completed_callbacks if s.target_callback_id else False)
        ),
        None,
    )
    if closure is not None:
        refs["callback_id"] = str(closure.target_callback_id)
        refs["staff_action_id"] = closure.id
        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.CLOSED_BY_STAFF,
                severity=Severity.NONE,
                requires_staff_action=False,
                reason="A staff member completed the callback for this call.",
                next_step="No further action.",
                evidence_refs=refs,
            ),
            suppress_mismatch=True,
        )

    transfers = _attempted(executions, ActionKind.TRANSFER_TRIAGE)
    schedulings = _attempted(executions, ActionKind.SCHEDULE_APPOINTMENT)
    callbacks = _attempted(executions, ActionKind.CREATE_CALLBACK)

    connected = [t for t in evidence.transfer_sessions if t.status == TransferStatus.CONNECTED]
    created_callbacks = [
        c for c in evidence.callback_requests if c.status == CallbackStatus.CREATED
    ]
    booked = [a for a in evidence.appointments if a.status == AppointmentStatus.BOOKED]

    # ---- 3. A triage transfer was attempted: the high-risk path. --------------
    if transfers:
        refs["transfer_execution_id"] = transfers[0].id

        if connected:
            refs["transfer_session_id"] = connected[0].id
            return _with_overlay(
                evidence,
                DerivedStatus(
                    status=CallStatus.COMPLETED_TRANSFERRED,
                    severity=Severity.NONE,
                    requires_staff_action=False,
                    reason="The caller was connected to the triage line and the line confirmed it.",
                    next_step="No further action.",
                    evidence_refs=refs,
                ),
            )

        failure = _transfer_failure_phrase(evidence)
        if created_callbacks:
            callback = created_callbacks[0]
            refs["callback_id"] = callback.id
            urgent = callback.priority == CallbackPriority.URGENT
            return _with_overlay(
                evidence,
                DerivedStatus(
                    status=CallStatus.CALLBACK_PENDING,
                    severity=Severity.URGENT if urgent else Severity.ROUTINE,
                    requires_staff_action=True,
                    reason=(
                        f"The transfer to triage did not complete ({failure}). "
                        f"{'An urgent' if urgent else 'A normal-priority'} callback request "
                        "was created and is still open."
                    ),
                    next_step="Call the patient back on the number recorded for this call.",
                    evidence_refs=refs,
                ),
            )

        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.ESCALATION_FAILED,
                severity=Severity.CRITICAL,
                requires_staff_action=True,
                reason=(
                    f"The transfer to triage did not complete ({failure}) and no callback "
                    "request was created. Nothing is queued for this caller."
                ),
                next_step="Call the patient back immediately; this caller has had no clinical contact.",
                evidence_refs=refs,
            ),
        )

    # ---- 4. Classified post-operative, yet no transfer was ever attempted. ----
    if evidence.call.agent_classified_intent == Intent.POST_OPERATIVE_CONCERN:
        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.ROUTING_GAP,
                severity=Severity.HIGH,
                requires_staff_action=True,
                reason=(
                    "The agent recorded this as a post-operative concern but never attempted a "
                    "triage transfer, which the practice policy requires."
                ),
                next_step="Call the patient back and review why the flow did not route to triage.",
                evidence_refs=refs,
            ),
        )

    # ---- 5. Routine scheduling. ----------------------------------------------
    if schedulings:
        refs["scheduling_execution_id"] = schedulings[0].id
        if booked:
            refs["appointment_id"] = booked[0].id
            return _with_overlay(
                evidence,
                DerivedStatus(
                    status=CallStatus.COMPLETED_SCHEDULED,
                    severity=Severity.NONE,
                    requires_staff_action=False,
                    reason="An appointment was booked and the scheduler confirmed it.",
                    next_step="No further action.",
                    evidence_refs=refs,
                ),
            )
        if created_callbacks:
            refs["callback_id"] = created_callbacks[0].id
        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.SCHEDULING_INCOMPLETE,
                severity=Severity.ROUTINE,
                requires_staff_action=True,
                reason=(
                    "Scheduling was attempted but no appointment exists in the scheduler."
                    + (
                        " A callback request was created for the office to follow up."
                        if created_callbacks
                        else ""
                    )
                ),
                next_step="Book the appointment manually and call the patient to confirm.",
                evidence_refs=refs,
            ),
        )

    # ---- 6. A callback was the only action (unsupported or caller-requested). -
    if callbacks:
        refs["callback_execution_id"] = callbacks[0].id
        if created_callbacks:
            callback = created_callbacks[0]
            refs["callback_id"] = callback.id
            urgent = callback.priority == CallbackPriority.URGENT
            return _with_overlay(
                evidence,
                DerivedStatus(
                    status=CallStatus.CALLBACK_PENDING,
                    severity=Severity.URGENT if urgent else Severity.ROUTINE,
                    requires_staff_action=True,
                    reason="A callback request was created for this caller and is still open.",
                    next_step="Call the patient back on the number recorded for this call.",
                    evidence_refs=refs,
                ),
            )
        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.CALLBACK_FAILED,
                severity=Severity.HIGH,
                requires_staff_action=True,
                reason=(
                    "A callback request was attempted but the callback queue did not accept it. "
                    "Nothing is queued for this caller."
                ),
                next_step="Call the patient back on the number recorded for this call.",
                evidence_refs=refs,
            ),
        )

    # ---- 7. The call ended with no action of any kind. -----------------------
    if not [e for e in executions if e.kind in ACTION_KINDS]:
        return _with_overlay(
            evidence,
            DerivedStatus(
                status=CallStatus.NO_ACTION_RECORDED,
                severity=Severity.HIGH,
                requires_staff_action=True,
                reason=(
                    "The call ended without any recorded action. Whatever the caller was told, "
                    "nothing was scheduled, transferred, or queued."
                ),
                next_step="Review the call and contact the patient if they needed something.",
                evidence_refs=refs,
            ),
        )

    # ---- 8. Defensive fallback: evidence exists but matches no rule. ----------
    return _with_overlay(
        evidence,
        DerivedStatus(
            status=CallStatus.NEEDS_REVIEW,
            severity=Severity.URGENT,
            requires_staff_action=True,
            reason="This call has recorded actions that do not match any known outcome pattern.",
            next_step="Open the evidence timeline and review manually.",
            evidence_refs=refs,
        ),
    )


def _transfer_failure_phrase(evidence: CallEvidence) -> str:
    """Describe why the transfer is not a success, for the staff-facing reason."""
    sessions = evidence.transfer_sessions
    if not sessions:
        return "the triage line was never reached"
    session = sessions[-1]
    if session.status == TransferStatus.UNVERIFIED:
        return "the triage line did not confirm the connection"
    return session.failure_reason or "no answer"


def _promise_stands(
    evidence: CallEvidence,
    promise: StatementKind,
    retraction: StatementKind | None,
) -> bool:
    """True when the agent made this promise and never took it back.

    An agent that says "I'll get you a callback" and then honestly says "I could
    not set up a callback" has told the truth. Only an uncorrected promise is a
    mismatch with the evidence.
    """
    promises = [s for s in evidence.agent_statements if s.kind == promise]
    if not promises:
        return False
    if retraction is None:
        return True
    last_promise = max(s.sequence_no for s in promises)
    return not any(
        s.sequence_no > last_promise for s in evidence.agent_statements if s.kind == retraction
    )


def _with_overlay(
    evidence: CallEvidence, base: DerivedStatus, *, suppress_mismatch: bool = False
) -> DerivedStatus:
    """Compare what the agent claimed against what the evidence shows.

    A mismatch never improves a status. It can only add attention and an
    explanation, because the discrepancy itself is something staff must see.
    """
    if suppress_mismatch:
        return base

    details: list[str] = []

    connected = any(t.status == TransferStatus.CONNECTED for t in evidence.transfer_sessions)
    has_callback = any(c.status == CallbackStatus.CREATED for c in evidence.callback_requests)
    has_appointment = any(a.status == AppointmentStatus.BOOKED for a in evidence.appointments)

    if (
        _promise_stands(
            evidence, StatementKind.PROMISED_TRANSFER, StatementKind.DISCLOSED_TRANSFER_FAILED
        )
        and not connected
    ):
        details.append(
            "The agent told the caller they were being transferred, but no transfer connected."
        )
    if (
        _promise_stands(
            evidence, StatementKind.PROMISED_CALLBACK, StatementKind.DISCLOSED_CALLBACK_FAILED
        )
        and not has_callback
    ):
        details.append("The agent promised a callback, but no callback request exists.")
    if _promise_stands(evidence, StatementKind.PROMISED_APPOINTMENT, None) and not has_appointment:
        details.append("The agent told the caller an appointment was made, but none exists.")

    claim = next(
        (
            s
            for s in evidence.agent_statements
            if s.kind == StatementKind.REPORTED_DISPOSITION and s.disposition in COMPLETION_CLAIMS
        ),
        None,
    )
    if claim is not None and base.requires_staff_action:
        details.append(
            f"The agent reported this call as '{claim.disposition}' while the recorded "
            "evidence shows it still needs a human."
        )

    if not details:
        return base

    return DerivedStatus(
        status=base.status,
        severity=max(base.severity, Severity.URGENT),
        requires_staff_action=True,
        reason=base.reason + " " + " ".join(details),
        next_step=base.next_step,
        promise_mismatch=True,
        mismatch_details=tuple(details),
        evidence_refs=base.evidence_refs,
    )
