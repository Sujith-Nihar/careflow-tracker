"""Shared shape for the simulated downstream systems.

These stand in for a scheduler, a clinical triage line and a callback queue. They
are deliberately explicit about the difference between "we asked" and "it worked",
because that distinction is the entire point of the project.

Behaviour is driven by a fault profile registered against the dial before the call
starts, so a scenario's failure is injected by the harness rather than invented by
the model mid-conversation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..domain.types import ActionOutcome

Sleeper = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class Attempt:
    attempt_no: int
    latency_ms: int
    result: str

    def as_dict(self) -> dict[str, Any]:
        return {"attempt_no": self.attempt_no, "latency_ms": self.latency_ms, "result": self.result}


@dataclass(frozen=True, slots=True)
class SimulatorResult:
    #: How the backend records the attempt.
    outcome: ActionOutcome
    #: The value the voice flow branches on. Kept separate from `outcome` because
    #: the wire vocabulary belongs to the flow, not to the database.
    status: str
    agent_message: str
    attempts: tuple[Attempt, ...] = ()
    failure_reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.outcome is ActionOutcome.SUCCEEDED

    def attempts_as_dicts(self) -> list[dict[str, Any]]:
        return [a.as_dict() for a in self.attempts]


class Clock:
    """Measures attempt latency and optionally burns the attempt budget.

    A simulated timeout really does take time during a voice run, because the
    agent's patience is part of what we are testing. Tests inject a no-op sleeper.
    """

    def __init__(self, sleeper: Sleeper = time.sleep) -> None:
        self._sleeper = sleeper

    def timed(self, seconds: float = 0.0) -> int:
        started = time.monotonic()
        if seconds > 0:
            self._sleeper(seconds)
        return int((time.monotonic() - started) * 1000)
