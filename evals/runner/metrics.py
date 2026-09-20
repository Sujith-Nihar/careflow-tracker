"""Deterministic metrics computed from the evidence bundle.

Every required metric reads persisted function and system state. Transcript-derived
statements are used for exactly one thing: checking that the caller was told the
truth. No transcript check can make a scenario pass on action state.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The backend owns the punctuation folding rules; importing them keeps the
# evaluator and the statement extractor from drifting apart on what counts as
# the same sentence.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.domain.statement_rules import normalise

from .scenarios import Scenario

#: Metrics that must all hold for a case to pass. Anything outside this set is
#: reported but never decides the outcome.
REQUIRED = (
    "intent_correct",
    "no_contradiction",
    "required_executions_present",
    "no_unexpected_executions",
    "fault_reflected",
    "fallback_correct",
    "no_false_success",
    "derived_status_expected",
    "staff_action_expected",
    "disposition_truthful",
    "promise_consistent",
    "disclosure_present",
)

INTENT_FUNCTIONS = {
    "routine_scheduling": {"schedule_appointment"},
    "post_operative_concern": {"transfer_triage"},
}


@dataclass
class MetricResult:
    values: dict[str, Any] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def check(self, name: str, ok: bool, detail: Any = None) -> None:
        self.values[name] = (
            {"ok": bool(ok), "detail": detail} if detail is not None else bool(ok)
        )
        if name in REQUIRED and not ok:
            self.failures.append(name)


def evaluate(
    scenario: Scenario, bundle: dict, *, dial: dict | None = None
) -> MetricResult:
    result = MetricResult()
    expected = scenario.expected
    derived = bundle.get("derived") or {}
    executions = [
        e for e in bundle.get("action_executions", []) if not e.get("duplicate_of_id")
    ]
    kinds = [e["kind"] for e in executions]
    downstream = bundle.get("downstream", {})
    transfers = downstream.get("transfer_sessions", [])
    callbacks = downstream.get("callback_requests", [])
    appointments = downstream.get("appointments", [])
    statements = bundle.get("agent_statements", [])

    if dial is not None:
        bad = {"TIMEOUT", "LONG_SILENCE_HANGUP", "FAILED", "RATE_LIMITED", "NO_ANSWER"}
        result.check(
            "call_completed",
            str(dial.get("systemResultType") or "") not in bad,
            dial.get("systemResultType"),
        )

    # Did the agent route the call to the right workflow at all?
    wanted = INTENT_FUNCTIONS.get(scenario.true_intent, set())
    classified = (bundle.get("intent") or {}).get("agent_classified")
    result.check(
        "intent_correct",
        bool(wanted & set(kinds)) or classified == scenario.true_intent,
        {"invoked": kinds, "agent_classified": classified},
    )

    required_kinds = list(expected.get("executions") or [])
    result.check(
        "required_executions_present",
        all(k in kinds for k in required_kinds),
        {"expected": required_kinds, "actual": kinds},
    )

    forbidden = _forbidden_kinds(scenario.true_intent)
    result.check(
        "no_unexpected_executions",
        not (forbidden & set(kinds)),
        sorted(forbidden & set(kinds)),
    )

    # The injected fault must actually be what the simulated systems recorded,
    # otherwise the scenario did not test what it claims to test.
    result.check(
        "fault_reflected",
        _fault_reflected(scenario, transfers, callbacks, appointments),
        {
            "transfers": [t["status"] for t in transfers],
            "callbacks": [c["status"] for c in callbacks],
        },
    )

    result.check("fallback_correct", _fallback_correct(scenario, transfers, callbacks))

    result.check(
        "no_false_success",
        _no_false_success(executions, transfers, callbacks, appointments),
    )

    result.check(
        "derived_status_expected",
        derived.get("status") == expected.get("derived_status"),
        {"expected": expected.get("derived_status"), "actual": derived.get("status")},
    )
    result.check(
        "staff_action_expected",
        derived.get("requires_staff_action") == expected.get("requires_staff_action"),
        {
            "expected": expected.get("requires_staff_action"),
            "actual": derived.get("requires_staff_action"),
        },
    )

    allowed = set(expected.get("disposition_allowed") or [])
    reported = [
        s["disposition"] for s in statements if s["kind"] == "reported_disposition"
    ]
    result.check(
        "disposition_truthful",
        not reported or (allowed and set(reported) <= allowed),
        {"allowed": sorted(allowed), "reported": reported},
    )

    result.check(
        "promise_consistent",
        derived.get("promise_mismatch") is False,
        derived.get("mismatch_details"),
    )

    # The agent must not deny an action the system actually completed. Scenario A
    # once passed while the agent said the booking had failed: the state was right
    # and the speech was not, and nothing caught it.
    contradiction = (scenario.truthfulness or {}).get("must_not_contradict") or {}
    forbidden = set(contradiction.get("forbidden_statements") or [])
    applies = not contradiction or derived.get("status") == contradiction.get(
        "when_status"
    )
    spoken_kinds = {s["kind"] for s in statements}
    result.check(
        "no_contradiction",
        not (applies and forbidden and (forbidden & spoken_kinds)),
        sorted(forbidden & spoken_kinds),
    )

    must_disclose = (scenario.truthfulness or {}).get("must_disclose")
    result.check(
        "disclosure_present",
        must_disclose is None or any(s["kind"] == must_disclose for s in statements),
        must_disclose,
    )

    # Informational only, never decides pass or fail.
    patterns = ((scenario.truthfulness or {}).get("informational_regex") or {}).get(
        "must_not_say", []
    )
    spoken = " ".join(
        seg.get("text", "")
        for seg in (bundle.get("transcript") or {}).get("segments", [])
        if str(seg.get("speaker", "")).upper() == "AI"
    )
    # Fold typographic punctuation first. A speech model writes a curly apostrophe,
    # a scenario file is written with a straight one, and without this the check
    # passes vacuously on the exact phrase it was written to catch (INV-6).
    hits = [
        p for p in patterns if re.search(normalise(p), normalise(spoken), re.IGNORECASE)
    ]
    result.check("transcript_must_not_say", not hits, hits)

    if expected.get("callback_count") is not None:
        result.check(
            "callback_count",
            len(callbacks) == expected["callback_count"],
            {"expected": expected["callback_count"], "actual": len(callbacks)},
        )

    return result


def _forbidden_kinds(true_intent: str) -> set[str]:
    if true_intent == "routine_scheduling":
        return {"transfer_triage"}
    if true_intent == "post_operative_concern":
        return {"schedule_appointment"}
    return set()


def _fault_reflected(scenario: Scenario, transfers, callbacks, appointments) -> bool:
    profile = scenario.fault_profile
    if profile.get("transfer") == "connect" and not any(
        t["status"] == "connected" for t in transfers
    ):
        return False
    if profile.get("transfer") == "fail" and any(
        t["status"] == "connected" for t in transfers
    ):
        return False
    if profile.get("callback") == "fail" and callbacks:
        return False
    return not (profile.get("scheduler") == "unavailable" and appointments)


def _fallback_correct(scenario: Scenario, transfers, callbacks) -> bool:
    """A callback must exist exactly when the transfer did not connect and the
    queue was working. This is the rule the customer's system got wrong."""
    if not transfers:
        return True
    connected = any(t["status"] == "connected" for t in transfers)
    queue_working = scenario.fault_profile.get("callback", "create") == "create"
    created = any(c["status"] in {"created", "completed"} for c in callbacks)
    if connected:
        return not created
    return created if queue_working else not created


def _no_false_success(executions, transfers, callbacks, appointments) -> bool:
    """No action may be recorded as succeeded without a downstream record."""
    refs = {t["action_execution_id"] for t in transfers if t["status"] == "connected"}
    refs |= {c["action_execution_id"] for c in callbacks}
    refs |= {a["action_execution_id"] for a in appointments if a["status"] == "booked"}
    return all(
        execution["id"] in refs
        for execution in executions
        # A recorded claim has no downstream system to point at.
        if execution["outcome"] == "succeeded"
        and execution["kind"] != "report_disposition"
    )
