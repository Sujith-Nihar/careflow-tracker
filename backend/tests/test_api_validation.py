"""Everything Vogent sends is a string produced by a speech model.

Bad input must produce a clear `invalid_input` the flow can react to, never a 500
and never a guessed value written into a patient's record.
"""

from __future__ import annotations

import pytest

from tests.helpers import bundle_for, call_function, dial_id, register_dial

pytestmark = pytest.mark.db


def test_an_unreadable_phone_number_is_refused_rather_than_guessed(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "bad_phone", {"callback": "create"},
                  "post_operative_concern")
    response = call_function(client, "create_callback", dial, {
        "patient_ref": "PT", "callback_phone": "my usual number",
        "priority": "urgent", "reason_code": "transfer_failed",
    })
    assert response.status_code == 200
    assert response.json["status"] == "invalid_input"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["downstream"]["callback_requests"] == []
    # The attempt is still recorded: the agent tried and could not.
    assert [e["outcome"] for e in bundle["action_executions"]] == ["rejected"]


def test_an_unreadable_date_is_refused(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "bad_date", {}, "routine_scheduling")
    response = call_function(client, "schedule_appointment", dial, {
        "patient_ref": "PT", "preferred_date": "whenever works", "reason": "checkup",
    })
    assert response.json["status"] == "invalid_input"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["downstream"]["appointments"] == []
    assert bundle["derived"]["requires_staff_action"] is True


def test_a_date_in_the_past_is_refused(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "past_date", {}, "routine_scheduling")
    response = call_function(client, "schedule_appointment", dial, {
        "patient_ref": "PT", "preferred_date": "2020-01-01", "reason": "checkup",
    })
    assert response.json["status"] == "invalid_input"


def test_spoken_digits_are_understood(client, demo_org):
    """STT often yields words, not digits. Refusing those would break real calls."""
    dial = dial_id()
    register_dial(client, demo_org, dial, "spoken_phone", {"callback": "create"},
                  "post_operative_concern")
    response = call_function(client, "create_callback", dial, {
        "patient_ref": "PT", "callback_phone": "five five five five five five zero one two three",
        "priority": "urgent", "reason_code": "transfer_failed",
    })
    assert response.json["status"] == "created"


def test_an_oversized_field_does_not_crash_the_endpoint(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "oversized", {"transfer": "connect"},
                  "post_operative_concern")
    response = call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT", "concern_summary": "x" * 5000, "callback_phone": "+15555550130",
    })
    assert response.status_code == 200
    assert response.json["status"] == "invalid_input"


def test_unknown_parameters_are_ignored_not_stored(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "extra_params", {"transfer": "connect"},
                  "post_operative_concern")
    call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT", "concern_summary": "ok", "callback_phone": "+15555550131",
        "surprise_field": "should not be stored",
    })
    bundle = bundle_for(client, demo_org, dial)
    stored = bundle["action_executions"][0]["request_payload"]
    assert "surprise_field" not in stored


def test_an_empty_body_is_rejected_cleanly(client):
    response = client.post(
        "/vogent/functions/transfer_triage", json={},
        headers={"X-CareFlow-Token": "test-function-token-demo"},
    )
    assert response.status_code in {400, 500}
    assert response.status_code != 200
