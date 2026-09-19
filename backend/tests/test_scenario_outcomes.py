"""End-state expectations for each evaluation scenario, on both flow versions.

These build the evidence a run would leave behind and assert what staff would see.
They are the written-down hypothesis for Experiment 1: if the real voice runs
disagree with these, the disagreement is a finding worth investigating, not a
test to quietly edit.

They are domain-level only. They prove the derivation, not the agent. Only a real
Vogent voice run can show that the agent invokes the right function at all.
"""

from __future__ import annotations

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
    StatementKind,
    TransferStatus,
)
from tests import factories as f


# --- Scenario A: routine scheduling ------------------------------------------------
def test_scenario_a_is_completed_on_both_versions():
    for version in ("v1", "v2"):
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
        assert result.status is CallStatus.COMPLETED_SCHEDULED, version
        assert result.requires_staff_action is False, version
        assert result.promise_mismatch is False, version


def test_scenario_a_v1_readback_becomes_a_lie_if_the_scheduler_refuses():
    # V1 reads the requested slot back before the scheduler answers. When the
    # scheduler declines, the caller has been told something untrue.
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.ROUTINE_SCHEDULING),
            executions=[f.execution(ActionKind.SCHEDULE_APPOINTMENT, ActionOutcome.FAILED)],
            statements=[f.said(StatementKind.PROMISED_APPOINTMENT, 1)],
        )
    )
    assert result.status is CallStatus.SCHEDULING_INCOMPLETE
    assert result.promise_mismatch is True


# --- Scenario B: post-operative concern, transfer connects --------------------------
def test_scenario_b_is_completed_on_both_versions():
    for version in ("v1", "v2"):
        execution = f.execution(ActionKind.TRANSFER_TRIAGE)
        result = derive_status(
            f.evidence(
                f.call(intent=Intent.POST_OPERATIVE_CONCERN),
                executions=[execution],
                transfers=[f.transfer(TransferStatus.CONNECTED, execution.id)],
                statements=[
                    f.said(StatementKind.PROMISED_TRANSFER, 1),
                    f.said(StatementKind.REPORTED_DISPOSITION, 2, Disposition.TRANSFERRED),
                ],
            )
        )
        assert result.status is CallStatus.COMPLETED_TRANSFERRED, version
        assert result.requires_staff_action is False, version
        assert result.promise_mismatch is False, version


# --- Scenario C: transfer fails, callback should catch the caller -------------------
def test_scenario_c_v1_leaves_the_caller_with_nothing_and_claims_success():
    # The customer's reported failure. V1 has no failure branch: it promised a
    # transfer, the transfer failed, no callback was ever attempted, and the
    # agent still reported the call resolved.
    execution = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.POST_OPERATIVE_CONCERN),
            executions=[execution],
            transfers=[f.transfer(TransferStatus.FAILED, execution.id, "no_answer")],
            statements=[
                f.said(StatementKind.PROMISED_TRANSFER, 1),
                f.said(StatementKind.REPORTED_DISPOSITION, 2, Disposition.RESOLVED),
            ],
        )
    )
    assert result.status is CallStatus.ESCALATION_FAILED
    assert result.severity == 4
    assert result.requires_staff_action is True
    assert result.promise_mismatch is True


def test_scenario_c_v2_catches_the_caller_with_an_urgent_callback():
    transfer_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    callback_exec = f.execution(ActionKind.CREATE_CALLBACK, seconds=12)
    result = derive_status(
        f.evidence(
            f.call(intent=Intent.POST_OPERATIVE_CONCERN),
            executions=[transfer_exec, callback_exec],
            transfers=[f.transfer(TransferStatus.FAILED, transfer_exec.id, "no_answer")],
            callbacks=[f.callback(CallbackStatus.CREATED, callback_exec.id, CallbackPriority.URGENT)],
            statements=[
                f.said(StatementKind.DISCLOSED_TRANSFER_FAILED, 1),
                f.said(StatementKind.PROMISED_CALLBACK, 2),
                f.said(StatementKind.REPORTED_DISPOSITION, 3, Disposition.CALLBACK_PENDING),
            ],
        )
    )
    assert result.status is CallStatus.CALLBACK_PENDING
    assert result.severity == 2
    assert result.requires_staff_action is True
    assert result.promise_mismatch is False


# --- Scenario D: the subtle one, both the transfer and the fallback fail ------------
def test_scenario_d_both_versions_end_critical_but_only_v2_is_honest():
    # This is why D is the subtle case. The derived status is identical on both
    # versions, so a suite that only checked status would call V1 and V2 equal.
    # The difference is whether the caller was told the truth.
    v1_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    v1 = derive_status(
        f.evidence(
            f.call(intent=Intent.POST_OPERATIVE_CONCERN),
            executions=[v1_exec],
            transfers=[f.transfer(TransferStatus.FAILED, v1_exec.id, "no_answer")],
            statements=[
                f.said(StatementKind.PROMISED_TRANSFER, 1),
                f.said(StatementKind.REPORTED_DISPOSITION, 2, Disposition.RESOLVED),
            ],
        )
    )

    v2_transfer = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    v2_callback = f.execution(ActionKind.CREATE_CALLBACK, ActionOutcome.FAILED, seconds=12)
    v2 = derive_status(
        f.evidence(
            f.call(intent=Intent.POST_OPERATIVE_CONCERN),
            executions=[v2_transfer, v2_callback],
            transfers=[f.transfer(TransferStatus.FAILED, v2_transfer.id, "no_answer")],
            statements=[
                f.said(StatementKind.DISCLOSED_TRANSFER_FAILED, 1),
                f.said(StatementKind.PROMISED_CALLBACK, 2),
                f.said(StatementKind.DISCLOSED_CALLBACK_FAILED, 3),
                f.said(StatementKind.REPORTED_DISPOSITION, 4, Disposition.ESCALATION_FAILED),
            ],
        )
    )

    assert v1.status is v2.status is CallStatus.ESCALATION_FAILED
    assert v1.severity == v2.severity == 4
    assert v1.promise_mismatch is True
    assert v2.promise_mismatch is False


def test_scenario_d_v2_records_that_the_fallback_was_attempted_but_does_not_exist():
    # "Fallback attempted" and "fallback created" must not be confusable.
    v2_transfer = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    v2_callback = f.execution(ActionKind.CREATE_CALLBACK, ActionOutcome.FAILED, seconds=12)
    bundle = f.evidence(
        f.call(intent=Intent.POST_OPERATIVE_CONCERN),
        executions=[v2_transfer, v2_callback],
        transfers=[f.transfer(TransferStatus.FAILED, v2_transfer.id)],
    )
    assert any(e.kind is ActionKind.CREATE_CALLBACK for e in bundle.action_executions)
    assert bundle.callback_requests == ()
    assert derive_status(bundle).status is CallStatus.ESCALATION_FAILED


# --- Scenario E: a duplicate function request from the vendor -----------------------
def test_scenario_e_duplicate_callback_leaves_exactly_one_queued_callback():
    transfer_exec = f.execution(ActionKind.TRANSFER_TRIAGE, ActionOutcome.FAILED)
    callback_exec = f.execution(ActionKind.CREATE_CALLBACK, seconds=12)
    duplicate = f.execution(ActionKind.CREATE_CALLBACK, seconds=13, duplicate_of_id=callback_exec.id)
    bundle = f.evidence(
        f.call(intent=Intent.POST_OPERATIVE_CONCERN),
        executions=[transfer_exec, callback_exec, duplicate],
        transfers=[f.transfer(TransferStatus.FAILED, transfer_exec.id)],
        callbacks=[f.callback(CallbackStatus.CREATED, callback_exec.id)],
    )
    result = derive_status(bundle)
    assert result.status is CallStatus.CALLBACK_PENDING
    assert len(bundle.callback_requests) == 1
