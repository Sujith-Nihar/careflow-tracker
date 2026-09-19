"""Logs must be useful for debugging without carrying anything sensitive.

The data here is synthetic, but the discipline is the point: an allow-list means
a newly added field cannot leak by being forgotten.
"""

from __future__ import annotations

import json

from app.observability.logging import (
    ALLOWED_FIELDS,
    DENIED_FIELDS,
    _enforce_allow_list,
)


def _filtered(**fields) -> dict:
    return _enforce_allow_list(None, None, fields)


def test_correlation_identifiers_survive():
    result = _filtered(event="action.completed", call_id="c1", dial_id="d1", outcome="failed")
    assert result["call_id"] == "c1"
    assert result["dial_id"] == "d1"
    assert result["outcome"] == "failed"


def test_a_phone_number_never_reaches_a_log_line():
    result = _filtered(event="action.requested", callback_phone="+15555550103")
    assert "callback_phone" not in result
    assert "+15555550103" not in json.dumps(result)


def test_free_text_and_payloads_are_dropped():
    result = _filtered(
        event="x",
        concern_summary="bleeding from the incision",
        request_payload={"patient_ref": "PT-1"},
        transcript=[{"text": "hello"}],
        evidence_text="I'm connecting you",
    )
    body = json.dumps(result)
    assert "bleeding" not in body
    assert "PT-1" not in body
    assert "connecting" not in body


def test_credentials_are_dropped():
    result = _filtered(event="x", token="secret-token", api_key="sk-live-123")
    assert "secret-token" not in json.dumps(result)
    assert "sk-live-123" not in json.dumps(result)


def test_dropped_field_names_are_reported_so_redaction_is_auditable():
    result = _filtered(event="x", callback_phone="+15555550103")
    assert result["dropped_fields"] == ["callback_phone"]


def test_the_allow_list_and_deny_list_do_not_overlap():
    assert ALLOWED_FIELDS.isdisjoint(DENIED_FIELDS)
