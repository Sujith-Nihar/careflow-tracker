"""One test per row of the derivation decision table, plus the mismatch overlay.

The invariant these tests defend: nothing the agent said can produce a completed
status, and a call with no evidence is never treated as finished.
"""

from __future__ import annotations

import pytest

from app.domain.derive_status import derive_status
from app.domain.types import (
    ActionKind,
    ActionOutcome,
    AppointmentStatus,
    CallbackPriority,
    CallbackStatus,
    CallStatus,
    Disposition,
    Intent,
    Lifecycle,
    StaffActionKind,
    StatementKind,
    TransferStatus,
)
from tests import factories as f


# --- Row 1: the call is still running -------------------------------------------------
@pytest.mark.parametrize("lifecycle", [Lifecycle.REGISTERED, Lifecycle.IN_PROGRESS])
def test_open_call_is_in_progress_and_not_actionable(lifecycle):
    result = derive_status(f.evidence(f.call(lifecycle=lifecycle)))
    assert result.status is CallStatus.IN_PROGRESS
    assert result.requires_staff_action is False


def test_open_call_does_not_raise_a_mismatch_mid_conversation():
    # The agent has promised a transfer but the call is still live; the function
    # may yet succeed. Flagging now would cry wolf on every in-flight call.
    result = derive_status(
        f.evidence(
            f.call(lifecycle=Lifecycle.IN_PROGRESS),
            statements=[f.said(StatementKind.PROMISED_TRANSFER)],
        )
    )
    assert result.promise_mismatch is False


# --- Row 2: staff closed the loop -----------------------------------------------------
def test_completed_callback_closed_by_staff():
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    done = f.callback(CallbackStatus.COMPLETED, execution.id)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.FAILED, execution.id, "no_answer")],
            callbacks=[done],
            staff_actions=[f.staff(StaffActionKind.CALLBACK_COMPLETED, done.id)],
        )
    )
    assert result.status is CallStatus.CLOSED_BY_STAFF
    assert result.requires_staff_action is False


def test_staff_action_without_a_completed_callback_does_not_close_the_call():
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    open_callback = f.callback(CallbackStatus.CREATED, execution.id)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.FAILED, execution.id)],
            callbacks=[open_callback],
            staff_actions=[f.staff(StaffActionKind.REVIEWED)],
        )
    )
    assert result.status is CallStatus.CALLBACK_PENDING
    assert result.requires_staff_action is True


# --- Row 3: the post-operative path ---------------------------------------------------
def test_connected_transfer_completes_the_call():
    execution = f.execution(ActionKind.TRANSFER_TRIAGE)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.CONNECTED, execution.id)],
        )
    )
    assert result.status is CallStatus.COMPLETED_TRANSFERRED
    assert result.requires_staff_action is False
    assert result.evidence_refs["transfer_session_id"]


def test_failed_transfer_with_urgent_callback_is_pending_not_resolved():
    transfer_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    callback_exec = f.execution(ActionKind.CREATE_CALLBACK, seconds=10)
    result = derive_status(
        f.evidence(
            executions=[transfer_exec, callback_exec],
            transfers=[f.transfer(TransferStatus.FAILED, transfer_exec.id, "no_answer")],
            callbacks=[f.callback(CallbackStatus.CREATED, callback_exec.id)],
        )
    )
    assert result.status is CallStatus.CALLBACK_PENDING
    assert result.severity == 2
    assert result.requires_staff_action is True
    # The reason must explain both halves: why the transfer failed, and that a
    # callback now exists. Asserted on meaning, not on exact wording.
    assert "nurse" in result.reason.lower()
    assert "callback" in result.reason.lower()
    # Staff-facing text carries no internal codes.
    assert "no_answer" not in result.reason


def test_failed_transfer_and_failed_callback_is_the_most_severe_state():
    # Scenario D. The fallback was attempted but nothing exists: no callback row.
    transfer_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    callback_exec = f.execution(ActionKind.CREATE_CALLBACK, ActionOutcome.FAILED, seconds=10)
    result = derive_status(
        f.evidence(
            executions=[transfer_exec, callback_exec],
            transfers=[f.transfer(TransferStatus.FAILED, transfer_exec.id, "no_answer")],
        )
    )
    assert result.status is CallStatus.ESCALATION_FAILED
    assert result.severity == 4
    assert result.requires_staff_action is True


def test_unverified_transfer_is_not_a_success():
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.UNVERIFIED)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.UNVERIFIED, execution.id)],
        )
    )
    assert result.status is CallStatus.ESCALATION_FAILED
    assert "never confirmed" in result.reason
    assert "unverified" not in result.reason


def test_rejected_transfer_request_still_demands_attention():
    # Invalid input means nothing was attempted downstream, so no session row exists.
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.REJECTED)
    result = derive_status(f.evidence(executions=[execution]))
    assert result.status is CallStatus.ESCALATION_FAILED


def test_transfer_outranks_scheduling_when_both_happened():
    # A caller with a surgical concern who also got an appointment is not "scheduled".
    transfer_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    schedule_exec = f.execution(ActionKind.SCHEDULE_APPOINTMENT, seconds=5)
    result = derive_status(
        f.evidence(
            executions=[transfer_exec, schedule_exec],
            transfers=[f.transfer(TransferStatus.FAILED, transfer_exec.id)],
            appointments=[f.appointment(AppointmentStatus.BOOKED, schedule_exec.id)],
        )
    )
    assert result.status is CallStatus.ESCALATION_FAILED


# --- Row 4: classified post-operative but never routed --------------------------------
def test_post_operative_call_with_no_transfer_is_a_routing_gap():
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.POST_OPERATIVE_CONCERN),
            executions=[f.execution(ActionKind.REPORT_DISPOSITION)],
            statements=[
                f.said(StatementKind.REPORTED_DISPOSITION, disposition=Disposition.UNRESOLVED)
            ],
        )
    )
    assert result.status is CallStatus.ROUTING_GAP
    assert result.severity == 3
    assert result.requires_staff_action is True


def test_post_operative_call_scheduled_instead_of_transferred_is_a_routing_gap():
    schedule_exec = f.execution(ActionKind.SCHEDULE_APPOINTMENT)
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.POST_OPERATIVE_CONCERN),
            executions=[schedule_exec],
            appointments=[f.appointment(AppointmentStatus.BOOKED, schedule_exec.id)],
        )
    )
    assert result.status is CallStatus.ROUTING_GAP


# --- Row 5: routine scheduling --------------------------------------------------------
def test_booked_appointment_completes_the_call():
    execution = f.execution(ActionKind.SCHEDULE_APPOINTMENT)
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.ROUTINE_SCHEDULING),
            executions=[execution],
            appointments=[f.appointment(AppointmentStatus.BOOKED, execution.id)],
        )
    )
    assert result.status is CallStatus.COMPLETED_SCHEDULED
    assert result.requires_staff_action is False


def test_scheduling_without_an_appointment_needs_manual_booking():
    result = derive_status(
        f.evidence(executions=[f.execution(ActionKind.SCHEDULE_APPOINTMENT, ActionOutcome.FAILED)])
    )
    assert result.status is CallStatus.SCHEDULING_INCOMPLETE
    assert result.severity == 1
    assert result.requires_staff_action is True


def test_cancelled_appointment_is_not_a_booking():
    execution = f.execution(ActionKind.SCHEDULE_APPOINTMENT)
    result = derive_status(
        f.evidence(
            executions=[execution],
            appointments=[f.appointment(AppointmentStatus.CANCELLED, execution.id)],
        )
    )
    assert result.status is CallStatus.SCHEDULING_INCOMPLETE


def test_scheduling_failure_with_followup_callback_mentions_it():
    schedule_exec = f.execution(ActionKind.SCHEDULE_APPOINTMENT, ActionOutcome.FAILED)
    callback_exec = f.execution(ActionKind.CREATE_CALLBACK, seconds=5)
    result = derive_status(
        f.evidence(
            executions=[schedule_exec, callback_exec],
            callbacks=[
                f.callback(CallbackStatus.CREATED, callback_exec.id, CallbackPriority.NORMAL)
            ],
        )
    )
    assert result.status is CallStatus.SCHEDULING_INCOMPLETE
    assert "callback" in result.reason.lower()


# --- Row 6: a callback was the only action --------------------------------------------
def test_standalone_callback_created_is_pending_at_routine_severity():
    execution = f.execution(ActionKind.CREATE_CALLBACK)
    result = derive_status(
        f.evidence(
            executions=[execution],
            callbacks=[f.callback(CallbackStatus.CREATED, execution.id, CallbackPriority.NORMAL)],
        )
    )
    assert result.status is CallStatus.CALLBACK_PENDING
    assert result.severity == 1


def test_standalone_callback_failure_is_visible():
    result = derive_status(
        f.evidence(executions=[f.execution(ActionKind.CREATE_CALLBACK, ActionOutcome.FAILED)])
    )
    assert result.status is CallStatus.CALLBACK_FAILED
    assert result.requires_staff_action is True


# --- Row 7: nothing happened -----------------------------------------------------------
def test_call_that_ended_with_no_actions_needs_review():
    result = derive_status(f.evidence(f.call(lifecycle=Lifecycle.ENDED)))
    assert result.status is CallStatus.NO_ACTION_RECORDED
    assert result.requires_staff_action is True


def test_a_disposition_report_alone_is_not_an_action():
    # The agent filed a claim and did nothing else. A claim is not an action.
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.ROUTINE_SCHEDULING),
            executions=[f.execution(ActionKind.REPORT_DISPOSITION)],
            statements=[
                f.said(StatementKind.REPORTED_DISPOSITION, disposition=Disposition.RESOLVED)
            ],
        )
    )
    assert result.status is CallStatus.NO_ACTION_RECORDED
    assert result.requires_staff_action is True


def test_unconfirmed_ending_still_derives_a_status():
    result = derive_status(f.evidence(f.call(lifecycle=Lifecycle.ENDED_UNCONFIRMED)))
    assert result.status is CallStatus.NO_ACTION_RECORDED


# --- Duplicates ------------------------------------------------------------------------
def test_duplicate_executions_do_not_change_the_outcome():
    execution = f.execution(ActionKind.TRANSFER_TRIAGE)
    duplicate = f.execution(ActionKind.TRANSFER_TRIAGE, duplicate_of_id=execution.id)
    result = derive_status(
        f.evidence(
            executions=[execution, duplicate],
            transfers=[f.transfer(TransferStatus.CONNECTED, execution.id)],
        )
    )
    assert result.status is CallStatus.COMPLETED_TRANSFERRED


# --- The mismatch overlay ---------------------------------------------------------------
def test_promised_transfer_without_a_connection_is_a_mismatch():
    # This is the customer's reported bug, reduced to its smallest form.
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.FAILED, execution.id)],
            statements=[f.said(StatementKind.PROMISED_TRANSFER, 1)],
        )
    )
    assert result.promise_mismatch is True
    assert result.requires_staff_action is True
    assert result.status is CallStatus.ESCALATION_FAILED


def test_disposition_claiming_resolution_while_work_remains_is_a_mismatch():
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.FAILED, execution.id)],
            statements=[f.said(StatementKind.REPORTED_DISPOSITION, 2, Disposition.RESOLVED)],
        )
    )
    assert result.promise_mismatch is True
    # The mismatch is spelled out for staff rather than quoting an internal value.
    assert "signed this call off" in result.reason
    assert result.mismatch_details


def test_honest_retraction_is_not_a_mismatch():
    # "I'll request a callback" followed by "I could not set up a callback" is truthful.
    transfer_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    callback_exec = f.execution(ActionKind.CREATE_CALLBACK, ActionOutcome.FAILED, seconds=10)
    result = derive_status(
        f.evidence(
            executions=[transfer_exec, callback_exec],
            transfers=[f.transfer(TransferStatus.FAILED, transfer_exec.id)],
            statements=[
                f.said(StatementKind.PROMISED_CALLBACK, 1),
                f.said(StatementKind.DISCLOSED_TRANSFER_FAILED, 2),
                f.said(StatementKind.DISCLOSED_CALLBACK_FAILED, 3),
                f.said(StatementKind.REPORTED_DISPOSITION, 4, Disposition.ESCALATION_FAILED),
            ],
        )
    )
    assert result.status is CallStatus.ESCALATION_FAILED
    assert result.promise_mismatch is False


def test_a_promise_made_after_a_retraction_still_counts():
    result = derive_status(
        f.evidence(
            executions=[f.execution(ActionKind.CREATE_CALLBACK, ActionOutcome.FAILED)],
            statements=[
                f.said(StatementKind.DISCLOSED_CALLBACK_FAILED, 1),
                f.said(StatementKind.PROMISED_CALLBACK, 2),
            ],
        )
    )
    assert result.promise_mismatch is True


def test_truthful_successful_call_has_no_mismatch():
    execution = f.execution(ActionKind.SCHEDULE_APPOINTMENT)
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.ROUTINE_SCHEDULING),
            executions=[execution],
            appointments=[f.appointment(AppointmentStatus.BOOKED, execution.id)],
            statements=[
                f.said(StatementKind.PROMISED_APPOINTMENT, 1),
                f.said(StatementKind.REPORTED_DISPOSITION, 2, Disposition.SCHEDULED),
            ],
        )
    )
    assert result.status is CallStatus.COMPLETED_SCHEDULED
    assert result.promise_mismatch is False
    assert result.requires_staff_action is False


def test_a_mismatch_never_upgrades_a_call_to_completed():
    # Whatever the agent claims, a status is only ever made worse by a mismatch.
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    result = derive_status(
        f.evidence(
            executions=[execution],
            transfers=[f.transfer(TransferStatus.FAILED, execution.id)],
            statements=[
                f.said(StatementKind.PROMISED_TRANSFER, 1),
                f.said(StatementKind.REPORTED_DISPOSITION, 2, Disposition.TRANSFERRED),
            ],
        )
    )
    assert result.status is CallStatus.ESCALATION_FAILED
    assert result.severity == 4


# --- Row 8: the defensive fallback ------------------------------------------------
def test_unrecognised_evidence_pattern_is_flagged_rather_than_assumed_fine():
    # Reaching this rule means the decision table has a gap. The safe answer is to
    # ask a human, never to treat an unclassifiable call as finished.
    import app.domain.derive_status as module

    original = module.ACTION_KINDS
    # Simulate an action kind the decision table does not yet know how to read.
    module.ACTION_KINDS = original | {ActionKind.REPORT_DISPOSITION}
    try:
        result = derive_status(f.evidence(executions=[f.execution(ActionKind.REPORT_DISPOSITION)]))
    finally:
        module.ACTION_KINDS = original

    assert result.status is CallStatus.NEEDS_REVIEW
    assert result.requires_staff_action is True
