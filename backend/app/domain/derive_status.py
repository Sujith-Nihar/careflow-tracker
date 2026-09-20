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


def observed_intent(evidence: CallEvidence) -> Intent | None:
    """What the caller wanted, judged by what the agent actually did.

    Preferred over the agent's own classification for the same reason completion is:
    an action taken is evidence, a self-report is a claim. Falls back to the claim
    only when no action was taken at all, which is exactly when there is nothing
    better to go on.
    """
    executions = _primary(evidence.action_executions)
    if _attempted(executions, ActionKind.TRANSFER_TRIAGE):
        return Intent.POST_OPERATIVE_CONCERN
    if _attempted(executions, ActionKind.SCHEDULE_APPOINTMENT):
        return Intent.ROUTINE_SCHEDULING
    return evidence.call.agent_classified_intent


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
                reason="A staff member rang this patient back.",
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
                    reason="The caller was put through to the nurse and the line confirmed it.",
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
                        f"The caller was not put through to the nurse because {failure}. "
                        f"{'An urgent' if urgent else 'A routine'} callback is now waiting "
                        "for someone to make."
                    ),
                    next_step="Ring this patient back on the number they gave.",
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
                    f"The caller was not put through to the nurse because {failure}, and no "
                    "callback was created either. Nobody is going to contact this patient."
                ),
                next_step="Call this patient back now. Nobody has spoken to them.",
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
                    "The agent logged this as a concern after surgery but never tried to put the "
                    "caller through to the nurse, which the practice policy requires."
                ),
                next_step="Ring this patient back, then check why the call was not routed.",
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
                    reason="An appointment was booked and confirmed.",
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
                    "The agent tried to book an appointment and there is no appointment."
                    + (
                        " A callback was created so the office can follow up."
                        if created_callbacks
                        else ""
                    )
                ),
                next_step="Book the appointment by hand and ring the patient to confirm.",
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
                    reason="A callback is waiting for someone to make.",
                    next_step="Ring this patient back on the number they gave.",
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
                    "The agent tried to arrange a callback and it was not created. Nothing is "
                    "waiting for this caller."
                ),
                next_step="Ring this patient back on the number they gave.",
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
                    "The call ended and nothing was done. Whatever the caller was told, no "
                    "appointment, transfer or callback exists."
                ),
                next_step="Listen to the call and ring the patient back if they needed something.",
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
            reason="This call does not match anything we recognise.",
            next_step="Read the call and decide what needs doing.",
            evidence_refs=refs,
        ),
    )


#: Failure codes are for logs. Staff read a sentence, so each code has a plain phrase.
_FAILURE_PHRASE = {
    "no_answer": "the line did not pick up",
    "busy": "the line was busy",
    "no_confirmation": "the line never confirmed the caller was connected",
    "transfer_timeout": "the line did not respond in time",
}


def _transfer_failure_phrase(evidence: CallEvidence) -> str:
    """Say why the transfer is not a success, in words a person would use."""
    sessions = evidence.transfer_sessions
    if not sessions:
        return "the nurse's line was never reached"
    session = sessions[-1]
    if session.status == TransferStatus.UNVERIFIED:
        return "the line never confirmed the caller was connected"
    return _FAILURE_PHRASE.get(session.failure_reason or "", "the line did not pick up")


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
        details.append("The agent told the caller they were being put through, and they were not.")
    if (
        _promise_stands(
            evidence, StatementKind.PROMISED_CALLBACK, StatementKind.DISCLOSED_CALLBACK_FAILED
        )
        and not has_callback
    ):
        details.append("The agent promised a callback, and no callback was ever created.")
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
        details.append("The agent signed this call off as finished when it was not.")

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
