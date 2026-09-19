"""Worker configuration.

Nothing here is a secret. The queue endpoint is local in development and comes from
the task definition in AWS; the database URL and the practice tokens are read by the
evaluation runner from the environment, which in AWS means SSM SecureString parameters
injected at task start rather than baked into an image.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    endpoint_url: str | None
    region: str
    queue_name: str
    dlq_name: str
    #: How long a message stays invisible while a job runs. Must exceed the longest
    #: job, or a slow run is handed to a second worker and done twice.
    visibility_timeout: int
    #: Long-poll rather than spin: fewer empty receives, and in AWS, fewer charges.
    wait_seconds: int
    max_receives: int

    @classmethod
    def from_env(cls) -> WorkerConfig:
        return cls(
            endpoint_url=os.environ.get("SQS_ENDPOINT_URL") or None,
            region=os.environ.get("AWS_REGION", "us-east-1"),
            queue_name=os.environ.get("EVAL_QUEUE_NAME", "careflow-eval-jobs"),
            dlq_name=os.environ.get("EVAL_DLQ_NAME", "careflow-eval-jobs-dlq"),
            visibility_timeout=int(os.environ.get("EVAL_VISIBILITY_TIMEOUT", "120")),
            wait_seconds=int(os.environ.get("EVAL_WAIT_SECONDS", "5")),
            max_receives=int(os.environ.get("EVAL_MAX_RECEIVES", "3")),
        )
