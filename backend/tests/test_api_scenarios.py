"""The Vogent boundary, exercised end to end against a real PostgreSQL.

Each test drives the same function calls the voice agent makes, then reads the
evidence bundle the dashboard and evaluator read. Nothing asserts on a transcript.
"""

from __future__ import annotations

import pytest

from tests.helpers import bundle_for, call_function, dial_id, register_dial

pytestmark = pytest.mark.db


# --- Scenario A: routine scheduling ------------------------------------------------
def test_routine_scheduling_books_an_appointment(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "A_routine_scheduling", {}, "routine_scheduling")

    response = call_function(client, "schedule_appointment", dial, {
        "patient_ref": "PT-SYN-0001", "preferred_date": "next Tuesday", "reason": "routine follow up",
    })
    assert response.status_code == 200
    assert response.json["status"] == "booked"
    assert response.json["appointment_id"]

    call_function(client, "report_disposition", dial, {
        "category": "routine_scheduling", "disposition": "scheduled", "summary": "booked",
    })

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["derived"]["status"] == "completed_scheduled"
    assert bundle["derived"]["requires_staff_action"] is False
    assert len(bundle["downstream"]["appointments"]) == 1


# --- Scenario B: transfer connects --------------------------------------------------
def test_successful_transfer_completes_the_call(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "B_postop_transfer_ok",
                  {"transfer": "connect"}, "post_operative_concern")

    response = call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0002", "concern_summary": "incision question",
        "callback_phone": "+15555550102",
    })
    assert response.json["status"] == "connected"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["derived"]["status"] == "completed_transferred"
    assert bundle["derived"]["requires_staff_action"] is False
    assert bundle["downstream"]["transfer_sessions"][0]["status"] == "connected"


# --- Scenario C: transfer fails, callback catches the caller ------------------------
def test_failed_transfer_then_callback_is_pending_not_resolved(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "C_postop_transfer_fail_callback",
                  {"transfer": "fail", "callback": "create"}, "post_operative_concern")

    transfer = call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0003", "concern_summary": "bleeding",
        "callback_phone": "+15555550103",
    })
    assert transfer.json["status"] == "failed"
    assert transfer.json["failure_reason"] == "no_answer"
    # The failure is reported as a normal response so the flow can branch on it.
    assert transfer.status_code == 200

    callback = call_function(client, "create_callback", dial, {
        "patient_ref": "PT-SYN-0003", "callback_phone": "+15555550103",
        "priority": "urgent", "reason_code": "transfer_failed",
    })
    assert callback.json["status"] == "created"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["derived"]["status"] == "callback_pending"
    assert bundle["derived"]["requires_staff_action"] is True
    assert bundle["derived"]["severity"] == 2
    assert bundle["downstream"]["transfer_sessions"][0]["status"] == "failed"
    assert bundle["downstream"]["callback_requests"][0]["priority"] == "urgent"


# --- Scenario D: the subtle one, the fallback itself fails ---------------------------
def test_failed_transfer_and_failed_callback_leaves_nothing_queued(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "D_postop_double_failure",
                  {"transfer": "fail", "callback": "fail"}, "post_operative_concern")

    call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0004", "concern_summary": "fever",
        "callback_phone": "+15555550104",
    })
    callback = call_function(client, "create_callback", dial, {
        "patient_ref": "PT-SYN-0004", "callback_phone": "+15555550104",
        "priority": "urgent", "reason_code": "transfer_failed",
    })
    assert callback.json["status"] == "failed"

    bundle = bundle_for(client, demo_org, dial)
    # The attempt is recorded, but nothing exists in the queue. That distinction
    # is the whole point of this scenario.
    assert any(e["kind"] == "create_callback" for e in bundle["action_executions"])
    assert bundle["downstream"]["callback_requests"] == []
    assert bundle["derived"]["status"] == "escalation_failed"
    assert bundle["derived"]["severity"] == 4


def test_agent_claiming_resolution_after_a_failure_is_flagged(client, demo_org):
    """The customer's reported bug, reproduced through the real boundary."""
    dial = dial_id()
    register_dial(client, demo_org, dial, "V1_reproduction",
                  {"transfer": "fail"}, "post_operative_concern")

    call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0005", "concern_summary": "swelling",
        "callback_phone": "+15555550105",
    }, transcript=[{"speaker": "AI", "text": "I'm connecting you to our triage nurse now."}])

    call_function(client, "report_disposition", dial, {
        "category": "post_operative_concern", "disposition": "resolved", "summary": "transferred",
    })

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["derived"]["status"] == "escalation_failed"
    assert bundle["derived"]["promise_mismatch"] is True
    assert bundle["derived"]["requires_staff_action"] is True


# --- Unverified outcomes are not successes -------------------------------------------
def test_unverified_transfer_is_not_treated_as_connected(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "F_transfer_unverified",
                  {"transfer": "unverified"}, "post_operative_concern")

    response = call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0006", "concern_summary": "pain",
        "callback_phone": "+15555550106",
    })
    assert response.json["status"] == "unverified"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["downstream"]["transfer_sessions"][0]["status"] == "unverified"
    assert bundle["derived"]["status"] == "escalation_failed"


def test_a_call_with_no_actions_is_not_treated_as_finished(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "no_action", {}, "post_operative_concern")
    bundle = bundle_for(client, demo_org, dial)
    assert bundle["derived"]["status"] == "no_action_recorded"
    assert bundle["derived"]["requires_staff_action"] is True


# --- Staff closing the loop -----------------------------------------------------------
def test_staff_completing_the_callback_closes_the_call(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "C_postop_transfer_fail_callback",
                  {"transfer": "fail", "callback": "create"}, "post_operative_concern")
    call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0007", "concern_summary": "bleeding",
        "callback_phone": "+15555550107",
    })
    call_function(client, "create_callback", dial, {
        "patient_ref": "PT-SYN-0007", "callback_phone": "+15555550107",
        "priority": "urgent", "reason_code": "transfer_failed",
    })

    bundle = bundle_for(client, demo_org, dial)
    callback_id = bundle["downstream"]["callback_requests"][0]["id"]

    response = client.post(
        f"/api/calls/{bundle['call']['id']}/staff-actions",
        json={"kind": "callback_completed", "actor": "front-desk",
              "target_callback_id": callback_id},
        headers={"X-Organization-Id": demo_org},
    )
    assert response.status_code == 201
    assert response.json["derived"]["status"] == "closed_by_staff"
    assert response.json["derived"]["requires_staff_action"] is False

    # Completing it twice is refused rather than silently repeated.
    repeat = client.post(
        f"/api/calls/{bundle['call']['id']}/staff-actions",
        json={"kind": "callback_completed", "actor": "front-desk",
              "target_callback_id": callback_id},
        headers={"X-Organization-Id": demo_org},
    )
    assert repeat.status_code == 409


def test_a_webhook_and_the_runner_can_create_the_same_call_concurrently(client, demo_org):
    """Vogent announces the dial while the runner is still registering it.

    Both paths create the call row. Whichever loses must adopt the winner's row
    and fill in what the winner did not know, rather than failing the request.
    """
    dial = dial_id()
    # The vendor's announcement arrives first and knows nothing about the scenario.
    client.post(
        "/vogent/webhooks/test-webhook-token-demo",
        json={"event": "dial.created", "payload": {"dial_id": dial, "status": "in_progress"}},
    )
    response = register_dial(client, demo_org, dial, "race_check",
                             {"transfer": "connect"}, "post_operative_concern")
    assert response.status_code == 201

    resolved = client.get(f"/api/calls/by-dial/{dial}", headers={"X-Organization-Id": demo_org})
    detail = client.get(f"/api/calls/{resolved.json['call_id']}",
                        headers={"X-Organization-Id": demo_org}).json
    assert detail["call"]["scenario_id"] == "race_check"
    assert detail["intent"]["true_intent"] == "post_operative_concern"


def test_a_failed_transfer_still_leaves_a_call_detail_record(client, demo_org):
    """The attempt is evidence. Staff must see that the line was tried and did not answer."""
    dial = dial_id()
    register_dial(client, demo_org, dial, "failed_transfer_record",
                  {"transfer": "fail"}, "post_operative_concern")
    response = call_function(client, "transfer_triage", dial, {
        "concern_summary": "bleeding", "callback_phone": "+15555550150",
    })
    assert response.json["status"] == "failed"

    bundle = bundle_for(client, demo_org, dial)
    sessions = bundle["downstream"]["transfer_sessions"]
    assert len(sessions) == 1
    assert sessions[0]["status"] == "failed"
    assert sessions[0]["failure_reason"] == "no_answer"
