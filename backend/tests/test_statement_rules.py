"""The transcript rules are checked against the exact wordings both flows use.

These tests exist so a flow reword cannot silently stop the system from noticing
that a caller was promised something. They assert what was *said*, never what
was done.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.statement_rules import extract_statements
from app.domain.types import StatementKind

T0 = datetime(2026, 9, 19, 17, 0, tzinfo=UTC)


def kinds(*texts: str) -> set[StatementKind]:
    transcript = [{"text": t, "speaker": "AI"} for t in texts]
    return {s.kind for s in extract_statements(transcript, observed_at=T0)}


# --- V1 baseline wordings ---------------------------------------------------------
def test_v1_transfer_lifecycle_message_is_a_transfer_promise():
    assert StatementKind.PROMISED_TRANSFER in kinds("I'm connecting you to our triage nurse now.")


def test_v1_closing_line_promises_nothing_specific():
    assert kinds("They'll take it from here. Take care.") == set()


def test_v1_scheduling_readback_is_an_appointment_promise():
    assert StatementKind.PROMISED_APPOINTMENT in kinds("You're all set for Tuesday at ten.")


# --- V2 evidence-aware wordings ---------------------------------------------------
def test_v2_hedged_attempt_is_not_a_promise():
    # "Let me try" commits to nothing, so it must not be recorded as a promise.
    assert kinds("Let me try to reach our triage nurse.") == set()


def test_v2_verified_transfer_line_is_a_promise():
    assert StatementKind.PROMISED_TRANSFER in kinds("You're connected with our triage nurse now.")


def test_v2_failure_disclosure_is_recorded_and_not_read_as_a_promise():
    result = kinds("The transfer did not complete.")
    assert StatementKind.DISCLOSED_TRANSFER_FAILED in result
    assert StatementKind.PROMISED_TRANSFER not in result


def test_v2_intention_to_request_a_callback_is_not_yet_a_promise():
    assert StatementKind.PROMISED_CALLBACK not in kinds(
        "I'm going to request an urgent callback from our nurse."
    )


def test_v2_confirmed_callback_line_is_a_promise():
    assert StatementKind.PROMISED_CALLBACK in kinds(
        "A nurse will call you back at five five five, zero one zero three."
    )


def test_v2_double_failure_line_discloses_both_failures():
    result = kinds("I could not complete the transfer or set up a callback.")
    assert StatementKind.DISCLOSED_TRANSFER_FAILED in result
    assert StatementKind.DISCLOSED_CALLBACK_FAILED in result
    assert StatementKind.PROMISED_TRANSFER not in result
    assert StatementKind.PROMISED_CALLBACK not in result


def test_v2_booked_confirmation_is_an_appointment_promise():
    assert StatementKind.PROMISED_APPOINTMENT in kinds(
        "Your appointment is booked for Tuesday the twenty fourth."
    )


# --- Boundaries --------------------------------------------------------------------
def test_caller_speech_is_never_an_agent_statement():
    transcript = [
        {"text": "You said you would call me back.", "speaker": "HUMAN"},
        {"text": "Let me check on that.", "speaker": "AI"},
    ]
    assert extract_statements(transcript, observed_at=T0) == []


def test_a_sentence_that_admits_failure_does_not_also_promise_the_same_thing():
    result = kinds("I wasn't able to transfer you.")
    assert StatementKind.DISCLOSED_TRANSFER_FAILED in result
    assert StatementKind.PROMISED_TRANSFER not in result


def test_statements_are_sequenced_in_transcript_order():
    transcript = [
        {"text": "I'm connecting you to our triage nurse now.", "speaker": "AI"},
        {"text": "The transfer did not complete.", "speaker": "AI"},
        {"text": "A nurse will call you back shortly.", "speaker": "AI"},
    ]
    statements = extract_statements(transcript, observed_at=T0)
    order = [s.kind for s in statements]
    assert order == [
        StatementKind.PROMISED_TRANSFER,
        StatementKind.DISCLOSED_TRANSFER_FAILED,
        StatementKind.PROMISED_CALLBACK,
    ]
    assert [s.sequence_no for s in statements] == [0, 1, 2]


@pytest.mark.parametrize("text", ["", "   ", "Okay."])
def test_empty_and_neutral_speech_produces_nothing(text):
    assert kinds(text) == set()


def test_multiple_sentences_in_one_segment_are_scored_separately():
    result = kinds("The transfer did not complete. A nurse will call you back at that number.")
    assert StatementKind.DISCLOSED_TRANSFER_FAILED in result
    assert StatementKind.PROMISED_CALLBACK in result
