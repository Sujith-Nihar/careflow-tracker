"""Loading and validating scenario definitions.

A scenario is data, not code, so the same file drives a replay, a structural check
and a real voice call. Versioning it means a result can be tied to the exact
definition that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"


@dataclass(frozen=True, slots=True)
class CallerTurn:
    when: str
    say: str


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    version: int
    risk: str
    true_intent: str
    goal: str
    patient_ref: str
    callback_phone: str
    turns: tuple[CallerTurn, ...]
    fallback_say: str
    end_when: str
    max_turns: int
    fault_profile: dict[str, str]
    expected: dict[str, Any]
    truthfulness: dict[str, Any] = field(default_factory=dict)
    mode: str | None = None
    source_path: Path | None = None

    @property
    def voice_eligible(self) -> bool:
        """Scenario E tests a vendor retry, which cannot be provoked by talking."""
        return self.mode != "replay_only"


def load(scenario_id: str) -> Scenario:
    path = SCENARIO_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise UnknownScenario(scenario_id)
    return _parse(yaml.safe_load(path.read_text()), path)


def load_all() -> list[Scenario]:
    return [
        _parse(yaml.safe_load(p.read_text()), p)
        for p in sorted(SCENARIO_DIR.glob("*.yaml"))
    ]


class UnknownScenario(Exception):
    """Raised for a scenario id that does not exist. The worker turns this into a
    controlled failure rather than a crash, which is what the poisoned job tests."""

    def __init__(self, scenario_id: str) -> None:
        super().__init__(f"unknown scenario: {scenario_id}")
        self.scenario_id = scenario_id


def _parse(data: dict, path: Path) -> Scenario:
    caller = data.get("caller") or {}
    return Scenario(
        id=data["id"],
        version=int(data.get("version", 1)),
        risk=data.get("risk", "medium"),
        true_intent=data["true_intent"],
        goal=caller.get("goal", ""),
        patient_ref=caller.get("patient_ref", ""),
        callback_phone=caller.get("callback_phone", ""),
        turns=tuple(
            CallerTurn(when=t["when"], say=t["say"])
            for t in (caller.get("turns") or [])
        ),
        fallback_say=caller.get("fallback_say", ""),
        end_when=caller.get("end_when", ""),
        max_turns=int(caller.get("max_turns", 8)),
        fault_profile=dict(data.get("fault_profile") or {}),
        expected=dict(data.get("expected") or {}),
        truthfulness=dict(data.get("truthfulness") or {}),
        mode=data.get("mode"),
        source_path=path,
    )
