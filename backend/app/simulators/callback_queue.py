"""Simulated urgent callback queue.

This is the fallback the policy requires when a transfer cannot be verified. It
is also where the subtle failure lives: creating a callback can itself fail, and
a system that treats "we asked for a callback" as "a callback exists" will tell a
post-operative caller that a nurse is coming when nobody is.

A failed creation deliberately leaves nothing behind. The record of the attempt
lives on the action execution, not in the queue.
"""

from __future__ import annotations

from ..domain.types import ActionOutcome
from .base import Attempt, Clock, SimulatorResult

CREATE = "create"
FAIL = "fail"
TIMEOUT = "timeout"

#: The queue accepts a repeat of the same request idempotently, so one retry on a
#: timeout is safe. A transfer has no such guarantee, which is why it is not retried.
MAX_ATTEMPTS = 2


def create_callback(
    *,
    priority: str,
    fault: str = CREATE,
    clock: Clock | None = None,
    attempt_budget_seconds: float = 2.0,
) -> SimulatorResult:
    clock = clock or Clock()

    if fault == FAIL:
        latency = clock.timed(0.05)
        return SimulatorResult(
            outcome=ActionOutcome.FAILED,
            status="failed",
            agent_message="I could not place a callback request.",
            attempts=(Attempt(1, latency, "rejected"),),
            failure_reason="queue_rejected",
        )

    if fault == TIMEOUT:
        attempts = []
        for attempt_no in range(1, MAX_ATTEMPTS + 1):
            attempts.append(Attempt(attempt_no, clock.timed(attempt_budget_seconds), "timeout"))
        return SimulatorResult(
            outcome=ActionOutcome.UNVERIFIED,
            status="unverified",
            agent_message="I could not confirm the callback request.",
            attempts=tuple(attempts),
            failure_reason="queue_timeout",
        )

    latency = clock.timed(0.05)
    return SimulatorResult(
        outcome=ActionOutcome.SUCCEEDED,
        status="created",
        agent_message=f"A {priority} callback request is in the queue.",
        attempts=(Attempt(1, latency, "created"),),
    )
