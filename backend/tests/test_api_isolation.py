"""One practice must never see or write another practice's calls."""

from __future__ import annotations

import pytest

from tests.conftest import OTHER_FUNCTION_TOKEN
from tests.helpers import bundle_for, call_function, dial_id, register_dial

pytestmark = pytest.mark.db


def test_an_unknown_token_is_rejected(client):
    response = call_function(client, "transfer_triage", dial_id(), {}, token="not-a-real-token")
    assert response.status_code == 401
    assert "token" not in response.get_data(as_text=True).lower() or response.json["error"]


def test_a_missing_token_is_rejected(client):
    response = client.post("/vogent/functions/transfer_triage", json={"dial_id": "d", "params": {}})
    assert response.status_code == 401


def test_a_token_from_one_practice_cannot_write_against_another_practices_agent(
    client, demo_org, other_org
):
    """Defence in depth: the token alone would have been enough to accept this."""

    from app.persistence.db import transaction
    from app.persistence.repositories import register_agent

    with transaction() as conn:
        register_agent(conn, "agent-belongs-to-other", other_org)

    response = call_function(
        client,
        "transfer_triage",
        dial_id(),
        {"patient_ref": "PT", "concern_summary": "x", "callback_phone": "+15555550199"},
        agent_id="agent-belongs-to-other",
    )
    assert response.status_code == 403
    assert response.json["error"] == "agent_organization_mismatch"


def test_another_practice_cannot_read_a_call(client, demo_org, other_org):
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "isolation", {"transfer": "connect"}, "post_operative_concern"
    )
    call_function(
        client,
        "transfer_triage",
        dial,
        {
            "patient_ref": "PT-SYN-0020",
            "concern_summary": "x",
            "callback_phone": "+15555550120",
        },
    )
    bundle = bundle_for(client, demo_org, dial)
    call_id = bundle["call"]["id"]

    response = client.get(f"/api/calls/{call_id}", headers={"X-Organization-Id": other_org})
    # Not-found rather than forbidden, so the endpoint cannot be used to discover
    # which call ids exist elsewhere.
    assert response.status_code == 404


def test_another_practices_call_is_absent_from_the_list(client, demo_org, other_org):
    dial = dial_id()
    register_dial(
        client, demo_org, dial, "isolation_list", {"transfer": "connect"}, "post_operative_concern"
    )
    call_function(
        client,
        "transfer_triage",
        dial,
        {
            "patient_ref": "PT-SYN-0021",
            "concern_summary": "x",
            "callback_phone": "+15555550121",
        },
    )
    bundle_for(client, demo_org, dial)

    listing = client.get("/api/calls?limit=200", headers={"X-Organization-Id": other_org})
    assert listing.status_code == 200
    # The other practice may legitimately have its own calls; what matters is that
    # none of them are ours.
    assert all(c["dial_id"] != dial for c in listing.json["calls"])
    assert all(c["scenario_id"] != "isolation_list" for c in listing.json["calls"])


def test_a_malformed_organization_header_is_rejected_not_crashed(client):
    response = client.get("/api/calls", headers={"X-Organization-Id": "definitely-not-a-uuid"})
    assert response.status_code == 401


def test_the_other_practices_token_resolves_to_the_other_practice(client, other_org):
    dial = dial_id()
    response = call_function(
        client,
        "report_disposition",
        dial,
        {"category": "other", "disposition": "unresolved"},
        token=OTHER_FUNCTION_TOKEN,
        agent_id="agent-other-unregistered",
    )
    assert response.status_code == 200
    resolved = client.get(f"/api/calls/by-dial/{dial}", headers={"X-Organization-Id": other_org})
    assert resolved.status_code == 200


def test_one_practice_cannot_overwrite_anothers_injected_faults(client, demo_org, other_org):
    """Fault profiles are keyed by dial id, which is unique across the whole table.

    Without an ownership check on the upsert, a second practice registering the same
    dial would silently change what a call already in flight does to a patient.
    """
    dial = dial_id()
    first = register_dial(client, demo_org, dial, "isolation_faults", {"transfer": "fail"})
    assert first.status_code in (200, 201)

    second = register_dial(client, other_org, dial, "isolation_faults", {"transfer": "connect"})
    assert second.status_code == 403
    assert second.json["error"] == "organization_mismatch"

    # The original practice's faults are untouched.
    again = register_dial(client, demo_org, dial, "isolation_faults", {"transfer": "fail"})
    assert again.status_code in (200, 201)
