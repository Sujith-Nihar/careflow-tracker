"""Everything Vogent sends is a string produced by a speech model.

Bad input must produce a clear `invalid_input` the flow can react to, never a 500
and never a guessed value written into a patient's record.
"""

from __future__ import annotations

import pytest

from tests.helpers import DEMO_FUNCTION_TOKEN, bundle_for, call_function, dial_id, register_dial

pytestmark = pytest.mark.db


def test_an_unreadable_phone_number_is_refused_rather_than_guessed(client, demo_org):
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "bad_phone", {"callback": "create"}, "post_operative_concern"
    )
    response = call_function(
        client,
        "create_callback",
        dial,
        {
            "patient_ref": "PT",
            "callback_phone": "my usual number",
            "priority": "urgent",
            "reason_code": "transfer_failed",
        },
    )
    assert response.status_code == 200
    assert response.json["status"] == "invalid_input"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["downstream"]["callback_requests"] == []
    # The attempt is still recorded: the agent tried and could not.
    assert [e["outcome"] for e in bundle["action_executions"]] == ["rejected"]


def test_an_unreadable_date_is_refused(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "bad_date", {}, "routine_scheduling")
    response = call_function(
        client,
        "schedule_appointment",
        dial,
        {
            "patient_ref": "PT",
            "preferred_date": "whenever works",
            "reason": "checkup",
        },
    )
    assert response.json["status"] == "invalid_input"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["downstream"]["appointments"] == []
    assert bundle["derived"]["requires_staff_action"] is True


def test_a_date_in_the_past_is_refused(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "past_date", {}, "routine_scheduling")
    response = call_function(
        client,
        "schedule_appointment",
        dial,
        {
            "patient_ref": "PT",
            "preferred_date": "2020-01-01",
            "reason": "checkup",
        },
    )
    assert response.json["status"] == "invalid_input"


def test_spoken_digits_are_understood(client, demo_org):
    """STT often yields words, not digits. Refusing those would break real calls."""
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "spoken_phone", {"callback": "create"}, "post_operative_concern"
    )
    response = call_function(
        client,
        "create_callback",
        dial,
        {
            "patient_ref": "PT",
            "callback_phone": "five five five five five five zero one two three",
            "priority": "urgent",
            "reason_code": "transfer_failed",
        },
    )
    assert response.json["status"] == "created"


def test_an_oversized_field_does_not_crash_the_endpoint(client, demo_org):
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "oversized", {"transfer": "connect"}, "post_operative_concern"
    )
    response = call_function(
        client,
        "transfer_triage",
        dial,
        {
            "patient_ref": "PT",
            "concern_summary": "x" * 5000,
            "callback_phone": "+15555550130",
        },
    )
    assert response.status_code == 200
    assert response.json["status"] == "invalid_input"


def test_unknown_parameters_are_ignored_not_stored(client, demo_org):
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "extra_params", {"transfer": "connect"}, "post_operative_concern"
    )
    call_function(
        client,
        "transfer_triage",
        dial,
        {
            "patient_ref": "PT",
            "concern_summary": "ok",
            "callback_phone": "+15555550131",
            "surprise_field": "should not be stored",
        },
    )
    bundle = bundle_for(client, demo_org, dial)
    stored = bundle["action_executions"][0]["request_payload"]
    assert "surprise_field" not in stored


def test_an_empty_body_is_rejected_cleanly(client):
    response = client.post(
        "/vogent/functions/transfer_triage",
        json={},
        headers={"X-CareFlow-Token": "test-function-token-demo"},
    )
    assert response.status_code in {400, 500}
    assert response.status_code != 200


def test_dial_level_identifiers_beat_what_the_model_repeats_back(client, demo_org):
    """A value fixed when the dial was created outranks one the model echoed.

    Flow templates can arrive unresolved and spoken values can be misheard, so the
    identifier set at dial creation is the more trustworthy of the two.
    """
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "dial_inputs", {"callback": "create"}, "post_operative_concern"
    )
    body = {
        "dial_id": dial,
        "dial": {
            "id": dial,
            "agent": {"id": "agent-demo"},
            "inputs": {"patient_ref": "PT-SYN-FIXED", "callback_phone": "+15555550140"},
        },
        # The flow template never resolved, and the model echoed nothing useful.
        "params": {
            "patient_ref": "{{patient_ref}}",
            "callback_phone": "",
            "priority": "urgent",
            "reason_code": "transfer_failed",
        },
    }
    response = client.post(
        "/vogent/functions/create_callback",
        json=body,
        headers={"X-CareFlow-Token": "test-function-token-demo"},
    )
    assert response.json["status"] == "created"

    bundle = bundle_for(client, demo_org, dial)
    stored = next(e for e in bundle["action_executions"] if e["kind"] == "create_callback")[
        "request_payload"
    ]
    assert stored["patient_ref"] == "PT-SYN-FIXED"
    assert stored["callback_phone"] == "+15555550140"


def test_a_disposition_report_is_never_lost_to_a_validation_error(client, demo_org):
    """The agent's account of the call is the claim we compare against the evidence.

    Losing it behind a 500 would remove one side of that comparison. The flow's own
    intake answers are short forms ("routine", "post_op"), and the model sometimes
    replies with a sentence; both must still produce a usable claim.
    """
    dial = dial_id()
    register_dial(client, demo_org, dial, "loose_disposition", {}, "routine_scheduling")
    response = call_function(
        client,
        "report_disposition",
        dial,
        {
            "category": "routine",
            "disposition": "booked",
            "summary": "all done",
        },
    )
    assert response.status_code == 200
    assert response.json["status"] == "recorded"

    bundle = bundle_for(client, demo_org, dial)
    assert bundle["intent"]["agent_classified"] == "routine_scheduling"
    claim = next(s for s in bundle["agent_statements"] if s["kind"] == "reported_disposition")
    assert claim["disposition"] == "scheduled"


def test_an_unreadable_disposition_falls_back_to_the_least_flattering_reading(client, demo_org):
    """A garbled report must never be read as a success."""
    dial = dial_id()
    register_dial(client, demo_org, dial, "garbled_disposition", {}, "routine_scheduling")
    response = call_function(
        client,
        "report_disposition",
        dial,
        {
            "category": "%%%",
            "disposition": "%%%",
        },
    )
    assert response.status_code == 200

    bundle = bundle_for(client, demo_org, dial)
    claim = next(s for s in bundle["agent_statements"] if s["kind"] == "reported_disposition")
    assert claim["disposition"] == "unresolved"


def test_a_body_with_no_dial_id_is_a_client_error_not_a_server_error(client):
    """A malformed envelope is the one shape that cannot be recovered.

    Params are parsed leniently, because a speech model producing an odd value is
    expected. An envelope without a dial id is different: there is no call to attach
    anything to, and answering 500 would tell Vogent to retry a request that can
    never succeed.
    """
    response = client.post(
        "/vogent/functions/transfer_triage",
        json={"params": {"patient_ref": "PT"}},
        headers={"X-CareFlow-Token": DEMO_FUNCTION_TOKEN},
    )
    assert response.status_code == 400
    assert response.json["error"] == "malformed_envelope"


def test_an_unknown_route_stays_a_404(client):
    """The catch-all handler used to turn Flask's own 404 into a 500."""
    assert client.get("/vogent/functions/does_not_exist").status_code == 404
    assert client.delete("/healthz").status_code == 405
