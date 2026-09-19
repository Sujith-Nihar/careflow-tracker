"""Show what is sitting in the dead-letter queue and why.

This is the first thing an engineer runs when an evaluation job stops producing
results. It prints each poisoned message with its job id, so the same identifier can
be grepped out of the worker logs.
"""

from __future__ import annotations

import json

from .config import WorkerConfig
from .queues import client, queue_urls


def main() -> int:
    config = WorkerConfig.from_env()
    sqs = client(config)
    _, dlq_url = queue_urls(config)

    attributes = sqs.get_queue_attributes(
        QueueUrl=dlq_url, AttributeNames=["ApproximateNumberOfMessages"]
    )["Attributes"]
    depth = attributes.get("ApproximateNumberOfMessages", "0")
    print(f"dead-letter queue: {depth} message(s)")

    response = sqs.receive_message(
        QueueUrl=dlq_url, MaxNumberOfMessages=10, WaitTimeSeconds=1,
        VisibilityTimeout=1, AttributeNames=["ApproximateReceiveCount"],
    )
    for message in response.get("Messages") or []:
        received = message.get("Attributes", {}).get("ApproximateReceiveCount", "?")
        try:
            body = json.loads(message["Body"])
            job_id = body.get("job_id", "?")
            scenarios = ",".join(body.get("scenario_ids") or [])
        except json.JSONDecodeError:
            job_id, scenarios = "(unparseable)", message["Body"][:60]
        print(f"  job_id={job_id}  scenarios={scenarios}  receives={received}")
        print(f"    find the logs with: grep '\"job_id\": \"{job_id}\"' <worker log>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
