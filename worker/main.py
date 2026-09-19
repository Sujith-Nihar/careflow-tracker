"""Consume evaluation jobs from a queue and record their results.

The shape is the operable part: a message becomes a persisted evaluation run, a
failure becomes a persisted failed run *and* a dead-letter message, and every log
line carries the identifiers needed to connect the two.

Deletion policy: a message is deleted only after the run row is closed. If the
worker dies mid-job the message becomes visible again and is retried; after three
receives the redrive policy moves it to the dead-letter queue. That is at-least-once
delivery, and the run row is keyed by job so a retry updates rather than duplicates.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.observability.logging import bind, clear, configure, get_logger

from evals.runner.cli import build_client
from evals.runner.metrics import evaluate
from evals.runner.replay import replay
from evals.runner.scenarios import UnknownScenario, load

from .config import WorkerConfig
from .jobs import EvaluationJob, InvalidJob
from .queues import client as sqs_client
from .queues import ensure_queues

log = get_logger("careflow.worker")


def run_job(job: EvaluationJob, backend) -> dict[str, Any]:
    """Execute one job: open a run, replay each scenario, record each case, close it.

    An unknown scenario raises before any run is opened, so a malformed job never
    leaves a half-finished run behind.
    """
    scenarios = []
    for scenario_id in job.scenario_ids:
        try:
            scenarios.append(load(scenario_id))
        except UnknownScenario as exc:
            raise InvalidJob(str(exc)) from exc

    run_id = backend.open_run(
        run_id=job.evaluation_run_id, suite=job.suite, strategy="replay",
        cost_label="CALCULATED_ESTIMATE", job_id=job.job_id,
    )
    bind(evaluation_run_id=run_id)
    log.info("evaluation.run.started", strategy="replay", count=len(scenarios))

    started = time.monotonic()
    passed = 0
    for scenario in scenarios:
        bind(scenario_id=scenario.id)
        outcome = replay(backend, scenario, run_id=run_id)
        metrics = evaluate(scenario, outcome["bundle"])
        passed += int(metrics.passed)
        backend.record_case(
            run_id, scenario_id=scenario.id, scenario_version=scenario.version,
            mode="replay", passed=metrics.passed, metrics=metrics.values,
            dial_id=outcome["dial_id"], wall_seconds=outcome["wall_seconds"],
            connected_seconds=0, cost_usd=0.0,
        )
        log.info("evaluation.case.completed", mode="replay", passed=metrics.passed)

    wall = round(time.monotonic() - started, 3)
    backend.close_run(run_id, status="completed", wall_seconds=wall)
    log.info("evaluation.run.completed", wall_seconds=wall, count=len(scenarios))
    return {"evaluation_run_id": run_id, "passed": passed, "total": len(scenarios)}


def handle_message(message: dict, backend) -> None:
    receive_count = int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1"))
    bind(receive_count=receive_count)

    job = EvaluationJob.parse(message["Body"])
    bind(job_id=job.job_id)
    log.info("worker.job.received", mode=job.mode, count=len(job.scenario_ids))
    run_job(job, backend)


def main(max_messages: int | None = None) -> int:
    config = WorkerConfig.from_env()
    configure(os.environ.get("LOG_LEVEL", "INFO"))
    queue_url, _ = ensure_queues(config)
    sqs = sqs_client(config)
    backend = build_client()

    log.info("worker.started", count=max_messages or -1)
    handled = 0
    idle_polls = 0

    while max_messages is None or handled < max_messages:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=config.wait_seconds,
            VisibilityTimeout=config.visibility_timeout,
            AttributeNames=["ApproximateReceiveCount"],
        )
        messages = response.get("Messages") or []
        if not messages:
            idle_polls += 1
            # An empty poll does not mean an empty queue: a message that just failed
            # is invisible until its visibility timeout expires. Wait past that before
            # concluding there is no more work, or a retry is never observed.
            quiet_polls_needed = max(3, config.visibility_timeout // max(config.wait_seconds, 1) + 2)
            if max_messages is not None and idle_polls >= quiet_polls_needed:
                log.info("worker.idle", count=handled)
                break
            continue
        idle_polls = 0

        message = messages[0]
        clear()
        try:
            handle_message(message, backend)
        except InvalidJob as exc:
            # A job that can never succeed. Do not delete it: let the redrive policy
            # carry it to the dead-letter queue, which is where a human will look.
            log.info("worker.job.failed", error_type="InvalidJob", reason_code=str(exc)[:80])
            _mark_run_failed(message, backend, str(exc))
        except Exception as exc:  # noqa: BLE001 - any failure must be visible, not fatal
            log.info("worker.job.failed", error_type=type(exc).__name__)
            _mark_run_failed(message, backend, f"{type(exc).__name__}: {exc}"[:200])
        else:
            # Deleted only after the run row is closed.
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
            log.info("worker.job.completed")
        handled += 1

    clear()
    return 0


def _mark_run_failed(message: dict, backend, error: str) -> None:
    """Record the failure where an operator will see it, if the job named a run.

    The message itself is left on the queue so the redrive policy still applies. The
    run row is marked failed immediately rather than after three attempts, so the
    failure is visible on the first try instead of a minute later.
    """
    try:
        run_id = (EvaluationJob.parse(message["Body"]).evaluation_run_id) or None
    except InvalidJob:
        run_id = None
    if not run_id:
        return
    try:
        backend.close_run(run_id, status="failed", error=error)
    except Exception:  # noqa: BLE001 - reporting a failure must not raise a new one
        log.info("worker.job.failed", error_type="run_close_failed")


if __name__ == "__main__":
    raise SystemExit(main())
