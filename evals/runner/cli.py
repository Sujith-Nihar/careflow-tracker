"""`make replay` — run scenarios through the backend and print a results table.

This is the reviewer's two-minute path: no Vogent credentials, no browser, no
cost, but the same backend, simulators, derivation and metrics that the real
voice runs use.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _env import load_env, require  # noqa: E402

from .metrics import evaluate  # noqa: E402
from .replay import BackendClient, replay  # noqa: E402
from .scenarios import UnknownScenario, load, load_all  # noqa: E402


def build_client() -> BackendClient:
    load_env()
    return BackendClient(
        base_url=os.environ.get("BACKEND_URL", "http://localhost:5000").rstrip("/"),
        organization_id=require("DEMO_ORGANIZATION_ID"),
        function_token=require("CAREFLOW_DEMO_ORG_FUNCTION_TOKEN"),
        webhook_token=require("CAREFLOW_DEMO_ORG_WEBHOOK_TOKEN"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay scenarios through the backend")
    parser.add_argument("--scenarios", help="comma-separated scenario ids (default: all)")
    parser.add_argument("--artifacts", help="directory to write per-case evidence into")
    args = parser.parse_args(argv)

    try:
        scenarios = (
            [load(s.strip()) for s in args.scenarios.split(",")] if args.scenarios else load_all()
        )
    except UnknownScenario as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    client = build_client()
    run_id = str(uuid.uuid4())
    artifacts = Path(args.artifacts) if args.artifacts else None

    rows = []
    failures = 0
    for scenario in scenarios:
        outcome = replay(client, scenario, run_id=run_id)
        metrics = evaluate(scenario, outcome["bundle"])
        derived = outcome["bundle"].get("derived") or {}
        rows.append(
            (
                scenario.id,
                "PASS" if metrics.passed else "FAIL",
                derived.get("status", "?"),
                "yes" if derived.get("requires_staff_action") else "no",
                ",".join(metrics.failures) or "-",
                f"{outcome['wall_seconds']:.1f}s",
            )
        )
        failures += 0 if metrics.passed else 1

        if artifacts:
            case_dir = artifacts / run_id / scenario.id
            case_dir.mkdir(parents=True, exist_ok=True)
            (case_dir / "evidence.json").write_text(json.dumps(outcome["bundle"], indent=2))
            (case_dir / "functions.json").write_text(json.dumps(outcome["function_calls"], indent=2))
            (case_dir / "metrics.json").write_text(
                json.dumps(
                    {
                        "scenario_id": scenario.id, "scenario_version": scenario.version,
                        "evaluation_run_id": run_id, "dial_id": outcome["dial_id"],
                        "mode": "replay", "passed": metrics.passed,
                        "failures": metrics.failures, "metrics": metrics.values,
                    },
                    indent=2,
                )
            )

    _print_table(rows)
    print(f"\nevaluation_run_id {run_id}")
    if artifacts:
        print(f"artifacts written to {artifacts / run_id}")
    print(f"{len(rows) - failures}/{len(rows)} scenarios passed")
    return 1 if failures else 0


def _print_table(rows: list[tuple]) -> None:
    headers = ("scenario", "result", "derived status", "staff?", "failed metrics", "time")
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True)))


if __name__ == "__main__":
    raise SystemExit(main())
