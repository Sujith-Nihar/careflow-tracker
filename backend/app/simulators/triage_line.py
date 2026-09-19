"""Simulated live triage transfer.

The practice policy says a post-operative concern must reach a live triage nurse.
This simulates that line. Note what it does not do: it never reports success
unless the line answered. "Ringing" and "connected" are different facts, and an
unconfirmed transfer is treated as a failure for policy purposes.

The backend never retries a transfer. Ringing a clinical line twice is a real side
effect, and the policy already prescribes what to do when it does not answer.
"""

from __future__ import annotations

from ..domain.types import ActionOutcome
from .base import Attempt, Clock, SimulatorResult

CONNECT = "connect"
FAIL = "fail"
TIMEOUT = "timeout"
UNVERIFIED = "unverified"


def connect_to_triage(
    *,
    fault: str = CONNECT,
    clock: Clock | None = None,
    attempt_budget_seconds: float = 2.0,
) -> SimulatorResult:
    clock = clock or Clock()

    if fault == FAIL:
        latency = clock.timed(0.3)
        return SimulatorResult(
            outcome=ActionOutcome.FAILED,
            status="failed",
            agent_message="The triage line did not answer.",
            attempts=(Attempt(1, latency, "no_answer"),),
            failure_reason="no_answer",
        )

    if fault == TIMEOUT:
        latency = clock.timed(attempt_budget_seconds)
        return SimulatorResult(
            outcome=ActionOutcome.UNVERIFIED,
            status="unverified",
            agent_message="I could not confirm whether the triage line picked up.",
            attempts=(Attempt(1, latency, "timeout"),),
            failure_reason="transfer_timeout",
        )

    if fault == UNVERIFIED:
        # The bridge was accepted but the far end never confirmed. This is the
        # shape of failure most likely to be mistaken for success in a real system.
        latency = clock.timed(0.3)
        return SimulatorResult(
            outcome=ActionOutcome.UNVERIFIED,
            status="unverified",
            agent_message="I could not confirm whether the triage line picked up.",
            attempts=(Attempt(1, latency, "accepted_unconfirmed"),),
            failure_reason="no_confirmation",
        )

    latency = clock.timed(0.3)
    return SimulatorResult(
        outcome=ActionOutcome.SUCCEEDED,
        status="connected",
        agent_message="Connected to the triage nurse.",
        attempts=(Attempt(1, latency, "connected"),),
    )
