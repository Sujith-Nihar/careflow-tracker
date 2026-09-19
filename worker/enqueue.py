"""Put an evaluation job on the queue.

`python -m worker.enqueue --scenarios A_routine_scheduling,C_postop_transfer_fail_callback`
"""

from __future__ import annotations

import argparse
import uuid

from .config import WorkerConfig
from .jobs import EvaluationJob
from .queues import client, ensure_queues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enqueue an evaluation job")
    parser.add_argument("--scenarios", required=True, help="comma-separated scenario ids")
    parser.add_argument("--job-id", default=None)
    parser.add_argument(
        "--run-id", default=None,
        help="reuse an evaluation run id so artifacts and rows share one identifier",
    )
    args = parser.parse_args(argv)

    config = WorkerConfig.from_env()
    queue_url, _ = ensure_queues(config)
    job = EvaluationJob(
        job_id=args.job_id or f"job-{uuid.uuid4().hex[:10]}",
        scenario_ids=[s.strip() for s in args.scenarios.split(",") if s.strip()],
        evaluation_run_id=args.run_id or str(uuid.uuid4()),
    )
    client(config).send_message(QueueUrl=queue_url, MessageBody=job.as_body())
    print(f"queued {job.job_id}  scenarios={','.join(job.scenario_ids)}")
    print(f"  evaluation_run_id={job.evaluation_run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
