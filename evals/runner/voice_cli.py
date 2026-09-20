"""`make eval` — run scenarios as real Vogent browser voice calls.

Every case writes its own artifact directory and the suite writes a run summary
with wall-clock, connected seconds and dollars, which is what the cost experiment
later compares.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _env import load_env

from .cli import build_client
from .scenarios import UnknownScenario, load, load_all
from .vogent import VogentClient
from .voice import DEFAULT_RATE_USD_PER_SECOND, run_voice_case

ARTIFACT_ROOT = REPO_ROOT / "artifacts"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real Vogent voice evaluations")
    parser.add_argument("--version", default="v2", help="agent version: v1 or v2")
    parser.add_argument(
        "--scenarios", help="comma-separated scenario ids (default: voice-eligible)"
    )
    parser.add_argument(
        "--bucket", help="artifact sub-directory (default: the version)"
    )
    parser.add_argument("--headed", action="store_true", help="show the browser")
    parser.add_argument(
        "--strategy",
        default="naive_voice",
        choices=["naive_voice", "optimized"],
        help="naive_voice: a full voice call per scenario. optimized: risk-based mix.",
    )
    args = parser.parse_args(argv)

    load_env()
    try:
        scenarios = (
            [load(s.strip()) for s in args.scenarios.split(",")]
            if args.scenarios
            else [s for s in load_all() if s.voice_eligible]
        )
    except UnknownScenario as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    skipped = [s.id for s in scenarios if not s.voice_eligible]
    scenarios = [s for s in scenarios if s.voice_eligible]
    if skipped:
        print(f"skipping (replay-only): {', '.join(skipped)}")
    if not scenarios:
        print("error: no voice-eligible scenarios selected", file=sys.stderr)
        return 2

    backend = build_client()
    vogent = VogentClient()
    run_id = str(uuid.uuid4())
    root = ARTIFACT_ROOT / (args.bucket or args.version)
    versioned_prompt_id = vogent.versioned_prompt_id(args.version)

    # The run is persisted under the same id the artifacts use on disk, so a row in
    # the database and a directory of evidence are the same run.
    backend.open_run(
        run_id=run_id,
        suite="careflow",
        strategy="naive_voice",
        versioned_prompt_id=versioned_prompt_id,
        rate_usd_per_second=DEFAULT_RATE_USD_PER_SECOND,
        rate_source="https://docs.vogent.ai/platform-overview/billing (read 2026-09-18)",
        cost_label="CALCULATED_ESTIMATE",
    )

    if args.strategy == "optimized":
        from .optimized import run_optimised

        summary = run_optimised(
            scenarios,
            version=args.version,
            backend=backend,
            vogent=vogent,
            artifacts_root=ARTIFACT_ROOT / (args.bucket or "efficiency/optimized"),
            headless=not args.headed,
        )
        _print_optimised(summary)
        return 0 if summary["totals"]["passed"] == summary["totals"]["scenarios"] else 1

    print(f"run {run_id}  version {args.version}  {len(scenarios)} scenario(s)\n")
    cases = []
    for scenario in scenarios:
        print(f"  {scenario.id} ... ", end="", flush=True)
        case = run_voice_case(
            scenario,
            version=args.version,
            run_id=run_id,
            backend=backend,
            vogent=vogent,
            artifacts_root=root,
            headless=not args.headed,
        )
        cases.append(case)
        backend.record_case(
            run_id,
            scenario_id=case.scenario_id,
            scenario_version=case.scenario_version,
            mode="voice",
            passed=case.passed,
            metrics=case.metrics,
            dial_id=case.dial_id,
            call_id=case.call_id,
            wall_seconds=case.wall_seconds,
            connected_seconds=case.connected_seconds,
            cost_usd=case.cost_usd,
            artifact_path=case.artifact_path,
        )
        verdict = (
            "ERROR"
            if case.error and not case.metrics
            else ("PASS" if case.passed else "FAIL")
        )
        print(
            f"{verdict:5} {case.derived_status or '-':22} "
            f"dial {case.dial_id[:8]}  {case.connected_seconds or 0}s  "
            f"${case.cost_usd or 0:.4f}"
        )
        if case.failures:
            print(f"          failed metrics: {', '.join(case.failures)}")
        if case.error:
            print(f"          error: {case.error}")

    summary = _summarise(run_id, args.version, cases)
    backend.close_run(
        run_id, status="completed", wall_seconds=summary["totals"]["wall_seconds"]
    )
    (root / run_id / "run_summary.json").write_text(
        json.dumps(summary, indent=2, default=str)
    )
    _print_summary(summary)
    print(f"\nartifacts: {root / run_id}")
    return 0 if all(c.passed for c in cases) else 1


def _print_optimised(summary: dict) -> None:
    pre = summary["structural_preflight"]
    print(
        f"run {summary['evaluation_run_id']}  version {summary['agent_version']}  strategy optimized\n"
    )
    print(
        f"  structural preflight  {'PASS' if pre['passed'] else 'FAIL'}  "
        f"{pre['seconds']}s  {pre['findings']} finding(s)"
    )
    for case in summary["cases"]:
        verdict = "PASS" if case["passed"] else "FAIL"
        cost = f"${case['cost_usd']:.4f}" if case["cost_usd"] else "$0.0000"
        print(
            f"  {case['scenario_id']:34} {case['mode']:10} {verdict:5} "
            f"{case['derived_status'] or '-':22} {case['connected_seconds']:>3}s  {cost}"
        )
        if case["failures"]:
            print(f"      failed metrics: {', '.join(case['failures'])}")
    t = summary["totals"]
    print(
        f"\n{t['passed']}/{t['scenarios']} passed  |  {t['voice_calls']} voice call(s)  |  "
        f"wall {t['wall_seconds']:.0f}s  |  connected {t['connected_seconds']}s  |  "
        f"${t['cost_usd']:.4f} ({t['cost_label']})"
    )


def _summarise(run_id: str, version: str, cases: list) -> dict:
    connected = sum(c.connected_seconds or 0 for c in cases)
    cost = sum(c.cost_usd or 0 for c in cases)
    return {
        "evaluation_run_id": run_id,
        "strategy": "naive_voice",
        "agent_version": version,
        "versioned_prompt_id": cases[0].versioned_prompt_id if cases else None,
        "cases": [asdict(c) for c in cases],
        "totals": {
            "scenarios": len(cases),
            "passed": sum(1 for c in cases if c.passed),
            "wall_seconds": round(sum(c.wall_seconds for c in cases), 2),
            "connected_seconds": connected,
            "cost_usd": round(cost, 6),
            "cost_label": "CALCULATED_ESTIMATE",
            "rate_usd_per_second": DEFAULT_RATE_USD_PER_SECOND,
            "rate_source": "https://docs.vogent.ai/platform-overview/billing (read 2026-09-18)",
        },
    }


def _print_summary(summary: dict) -> None:
    totals = summary["totals"]
    print(
        f"\n{totals['passed']}/{totals['scenarios']} passed  |  "
        f"wall {totals['wall_seconds']:.0f}s  |  connected {totals['connected_seconds']}s  |  "
        f"${totals['cost_usd']:.4f} ({totals['cost_label']})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
