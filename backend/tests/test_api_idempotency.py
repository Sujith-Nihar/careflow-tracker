"""Duplicate delivery must not produce a second real-world action.

This is de-duplication, not an exactly-once guarantee. It holds for an identical
request on the same dial, which is the shape a vendor retry takes.
"""

from __future__ import annotations

import pytest

from tests.helpers import bundle_for, call_function, dial_id, register_dial

pytestmark = pytest.mark.db

CALLBACK_PARAMS = {
    "patient_ref": "PT-SYN-0010", "callback_phone": "+15555550110",
    "priority": "urgent", "reason_code": "transfer_failed",
}


def test_repeated_callback_request_creates_exactly_one_callback(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "E_duplicate_callback_request",
                  {"transfer": "fail", "callback": "create"}, "post_operative_concern")
    call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0010", "concern_summary": "bleeding",
        "callback_phone": "+15555550110",
    })

    first = call_function(client, "create_callback", dial, CALLBACK_PARAMS)
    second = call_function(client, "create_callback", dial, CALLBACK_PARAMS)

    assert first.json["status"] == second.json["status"] == "created"
    assert first.json["callback_id"] == second.json["callback_id"]

    bundle = bundle_for(client, demo_org, dial)
    assert len(bundle["downstream"]["callback_requests"]) == 1

    callbacks = [e for e in bundle["action_executions"] if e["kind"] == "create_callback"]
    assert len(callbacks) == 2, "the repeat is recorded, so the vendor's retry stays visible"
    assert sum(1 for e in callbacks if e["duplicate_of_id"]) == 1

    # The repeat does not change what staff must do.
    assert bundle["derived"]["status"] == "callback_pending"


def test_a_repeated_transfer_does_not_ring_the_triage_line_twice(client, demo_org):
    dial = dial_id()
    register_dial(client, demo_org, dial, "duplicate_transfer",
                  {"transfer": "connect"}, "post_operative_concern")
    params = {"patient_ref": "PT-SYN-0011", "concern_summary": "question",
              "callback_phone": "+15555550111"}

    call_function(client, "transfer_triage", dial, params)
    call_function(client, "transfer_triage", dial, params)

    bundle = bundle_for(client, demo_org, dial)
    assert len(bundle["downstream"]["transfer_sessions"]) == 1
    assert bundle["derived"]["status"] == "completed_transferred"


def test_different_parameters_are_a_different_action(client, demo_org):
    """De-duplication keys on the parameters, so a corrected request still runs."""
    dial = dial_id()
    register_dial(client, demo_org, dial, "corrected_callback",
                  {"transfer": "fail", "callback": "create"}, "post_operative_concern")
    call_function(client, "transfer_triage", dial, {
        "patient_ref": "PT-SYN-0012", "concern_summary": "pain",
        "callback_phone": "+15555550112",
    })
    call_function(client, "create_callback", dial, CALLBACK_PARAMS)
    call_function(client, "create_callback", dial, CALLBACK_PARAMS | {"priority": "normal"})

    bundle = bundle_for(client, demo_org, dial)
    assert len(bundle["downstream"]["callback_requests"]) == 2
