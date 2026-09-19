"""The optimised evaluation strategy.

Same scenarios, same frozen agent version, same metrics as the naive baseline.
What changes is how each scenario earns its evidence.

The selection rule is risk, not convenience:

* **Structural preflight** runs first, on every version, for free. It cannot prove
  an agent works, but it fails fast on a flow that is incapable of telling the
  truth, which makes the expensive calls pointless.
* **Replay** covers the scenarios whose flow path contains no failure branch. Their
  backend behaviour is fully exercised without voice, and a voice call adds
  recognition and timing coverage that these paths do not depend on.
* **Real voice** is kept for the high-risk transfer and callback paths. These are
  the scenarios where the practice's actual harm lives, and where every bug this
  project found was hiding.

Nothing is reused from the naive run. The cache starts cold and its population
cost is inside the measurement.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .metrics import evaluate
from .replay import BackendClient, replay
from .scenarios import Scenario
from .structural import check as structural_check
from .vogent import VogentClient
from .voice import DEFAULT_RATE_USD_PER_SECOND, run_voice_case

#: Scenarios whose flow path has no failure branch: replay covers them.
#: Anything else keeps a real voice call. This list is the coverage decision, and
#: it is stated here rather than buried in a filter.
REPLAY_ELIGIBLE = {"A_routine_scheduling", "B_postop_transfer_ok"}


@dataclass
class OptimisedCase:
    scenario_id: str
    mode: str
    passed: bool
    derived_status: str | None = None
    wall_seconds: float = 0.0
    connected_seconds: int = 0
    cost_usd: float = 0.0
    dial_id: str | None = None
    failures: list[str] = field(default_factory=list)
    reason: str = ""
    artifact_path: str | None = None


def run_optimised(
    scenarios: list[Scenario],
    *,
    version: str,
    backend: BackendClient,
    vogent: VogentClient,
    artifacts_root: Path,
    headless: bool = True,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    started = time.monotonic()
    root = artifacts_root / run_id
    root.mkdir(parents=True, exist_ok=True)

    # 1. Structural preflight. Milliseconds, no money, and it gates the rest.
    preflight_started = time.monotonic()
    report = structural_check(version)
    preflight_seconds = round(time.monotonic() - preflight_started, 4)
    (root / "structural.json").write_text(_dumps(report.as_dict()))

    cases: list[OptimisedCase] = []
    if not report.passed:
        # A flow that cannot speak the truth does not deserve voice calls.
        for scenario in scenarios:
            cases.append(
                OptimisedCase(
                    scenario_id=scenario.id,
                    mode="structural",
                    passed=False,
                    reason="structural preflight failed; voice calls skipped",
                    failures=[f.rule for f in report.findings],
                )
            )
        return _summarise(
            run_id, version, cases, started, preflight_seconds, report, root
        )

    for scenario in scenarios:
        if scenario.id in REPLAY_ELIGIBLE:
            cases.append(_replay_case(scenario, backend, run_id, root))
        else:
            cases.append(
                _voice_case(
                    scenario, version, run_id, backend, vogent, artifacts_root, headless
                )
            )

    return _summarise(run_id, version, cases, started, preflight_seconds, report, root)


def _replay_case(
    scenario: Scenario, backend: BackendClient, run_id: str, root: Path
) -> OptimisedCase:
    started = time.monotonic()
    outcome = replay(backend, scenario, run_id=run_id)
    metrics = evaluate(scenario, outcome["bundle"])
    derived = outcome["bundle"].get("derived") or {}

    case_dir = root / scenario.id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "evidence.json").write_text(_dumps(outcome["bundle"]))
    (case_dir / "functions.json").write_text(_dumps(outcome["function_calls"]))

    return OptimisedCase(
        scenario_id=scenario.id,
        mode="replay",
        passed=metrics.passed,
        derived_status=derived.get("status"),
        wall_seconds=round(time.monotonic() - started, 2),
        connected_seconds=0,
        cost_usd=0.0,
        failures=metrics.failures,
        reason="no failure branch on this path; backend behaviour fully exercised without voice",
        artifact_path=str(case_dir),
    )


def _voice_case(
    scenario: Scenario,
    version: str,
    run_id: str,
    backend: BackendClient,
    vogent: VogentClient,
    artifacts_root: Path,
    headless: bool,
) -> OptimisedCase:
    case = run_voice_case(
        scenario,
        version=version,
        run_id=run_id,
        backend=backend,
        vogent=vogent,
        artifacts_root=artifacts_root,
        headless=headless,
    )
    return OptimisedCase(
        scenario_id=scenario.id,
        mode="voice",
        passed=case.passed,
        derived_status=case.derived_status,
        wall_seconds=case.wall_seconds,
        connected_seconds=case.connected_seconds or 0,
        cost_usd=case.cost_usd or 0.0,
        dial_id=case.dial_id,
        failures=case.failures,
        reason="high-risk transfer and callback path; keeps real voice coverage",
        artifact_path=case.artifact_path,
    )


def _summarise(
    run_id: str,
    version: str,
    cases: list[OptimisedCase],
    started: float,
    preflight_seconds: float,
    report,
    root: Path,
) -> dict[str, Any]:
    summary = {
        "evaluation_run_id": run_id,
        "strategy": "optimized",
        "agent_version": version,
        "structural_preflight": {
            "passed": report.passed,
            "seconds": preflight_seconds,
            "findings": len(report.findings),
        },
        "replay_eligible": sorted(REPLAY_ELIGIBLE),
        "cases": [asdict(c) for c in cases],
        "totals": {
            "scenarios": len(cases),
            "passed": sum(1 for c in cases if c.passed),
            "voice_calls": sum(1 for c in cases if c.mode == "voice"),
            "wall_seconds": round(time.monotonic() - started, 2),
            "connected_seconds": sum(c.connected_seconds for c in cases),
            "cost_usd": round(sum(c.cost_usd for c in cases), 6),
            "cost_label": "CALCULATED_ESTIMATE",
            "rate_usd_per_second": DEFAULT_RATE_USD_PER_SECOND,
            "rate_source": "https://docs.vogent.ai/platform-overview/billing (read 2026-09-18)",
        },
    }
    (root / "run_summary.json").write_text(_dumps(summary))
    return summary


def _dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, default=str)
