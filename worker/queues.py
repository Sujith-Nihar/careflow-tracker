"""Queue setup, identical in shape locally and in AWS.

Locally this talks to a moto server; in AWS the same calls hit real SQS and the
queues are created by Terraform instead. The redrive policy is the important part:
a job that fails three times stops being retried and lands in the dead-letter queue,
where it can be inspected instead of looping forever.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

from .config import WorkerConfig


def client(config: WorkerConfig) -> Any:
    return boto3.client(
        "sqs",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "local"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local"),
    )


def ensure_queues(config: WorkerConfig) -> tuple[str, str]:
    """Create the work queue and its dead-letter queue, wired by a redrive policy.

    In AWS this is Terraform's job; locally the worker does it so `make worker-demo`
    is a single command. The shape is the same either way.
    """
    sqs = client(config)
    dlq_url = sqs.create_queue(QueueName=config.dlq_name)["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])[
        "Attributes"
    ]["QueueArn"]

    queue_url = sqs.create_queue(
        QueueName=config.queue_name,
        Attributes={
            "VisibilityTimeout": str(config.visibility_timeout),
            "RedrivePolicy": json.dumps(
                {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": str(config.max_receives)}
            ),
        },
    )["QueueUrl"]
    return queue_url, dlq_url


def queue_urls(config: WorkerConfig) -> tuple[str, str]:
    sqs = client(config)
    return (
        sqs.get_queue_url(QueueName=config.queue_name)["QueueUrl"],
        sqs.get_queue_url(QueueName=config.dlq_name)["QueueUrl"],
    )
