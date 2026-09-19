"""Simulated appointment scheduler.

Stands in for a practice management system. The boundary is deliberate: a real
integration would confirm a booking against the practice's calendar, and this
returns a synthetic confirmation instead. What it does faithfully reproduce is
that a booking either exists afterwards or it does not.
"""

from __future__ import annotations

from datetime import datetime

from ..domain.types import ActionOutcome
from .base import Attempt, Clock, SimulatorResult

# Fault profile values understood by this simulator.
BOOK = "book"
UNAVAILABLE = "unavailable"
TIMEOUT = "timeout"


def book_appointment(
    *,
    slot: datetime,
    fault: str = BOOK,
    clock: Clock | None = None,
    attempt_budget_seconds: float = 2.0,
) -> SimulatorResult:
    clock = clock or Clock()

    if fault == UNAVAILABLE:
        latency = clock.timed(0.05)
        return SimulatorResult(
            outcome=ActionOutcome.FAILED,
            status="unavailable",
            agent_message="That time is not available and I could not confirm another one.",
            attempts=(Attempt(1, latency, "unavailable"),),
            failure_reason="slot_unavailable",
        )

    if fault == TIMEOUT:
        latency = clock.timed(attempt_budget_seconds)
        # No answer within the budget. The booking may or may not exist; either way
        # it is not confirmed, and an unconfirmed booking is not a booking.
        return SimulatorResult(
            outcome=ActionOutcome.UNVERIFIED,
            status="unverified",
            agent_message="I could not confirm the booking just now.",
            attempts=(Attempt(1, latency, "timeout"),),
            failure_reason="scheduler_timeout",
        )

    latency = clock.timed(0.05)
    return SimulatorResult(
        outcome=ActionOutcome.SUCCEEDED,
        status="booked",
        agent_message=f"Booked for {slot.strftime('%A %d %B at %-I:%M %p')}.",
        attempts=(Attempt(1, latency, "booked"),),
        detail={"slot_iso": slot.isoformat()},
    )
