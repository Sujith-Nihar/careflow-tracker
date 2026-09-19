# Asynchronous Evaluation Path and Infrastructure

Owner of: queue → worker → persisted result design, its local demonstration, and the Terraform that
represents it in AWS. Live deployment is not planned.

## Shape

```
POST /api/evaluation-runs (mode=replay, async=true)  or  `make enqueue-eval`
        │ SendMessage {job_id, evaluation_run_id, scenario_ids, mode}
        ▼
   SQS queue  ──(3 failed receives)──▶  dead-letter queue
        │
        ▼
   worker (Python, long-poll)  ──▶  evaluation runner (replay mode)  ──▶  Flask /api  ──▶  PostgreSQL
        │
        └── JSON logs: worker.job.received / evaluation.run.completed / worker.job.failed
```

## Local demonstration (Phase 9)

- Queue: `moto[server]` running locally as an SQS-compatible endpoint (pure Python, no Docker). Both
  queues created by `worker/bootstrap.py` with a redrive policy `maxReceiveCount = 3`.
- Worker: `worker/main.py`, boto3 with `endpoint_url = SQS_ENDPOINT_URL`, visibility timeout 60 s,
  deletes the message only after the run row is `completed`; raises on failure so the message returns.
- Success job: scenario `A` in replay mode → `evaluation_runs.status = completed`, cases written.
- Poison job: `scenario_ids: ["Z_does_not_exist"]` → runner raises `UnknownScenario`; after three receives
  the message lands in the DLQ; the worker marks the run `failed` with the error on the first failure so
  the state is visible immediately, and a `dlq_inspect` command lists DLQ messages with their `job_id`.
- Correlation: every log line carries `job_id` and `evaluation_run_id`; `make worker-logs RUN=<id>` filters.
- Evidence saved to `artifacts/worker/`: worker log excerpt, queue attribute dumps before/after, DLQ message.

Fallback if `moto` redrive proves unfaithful: ElasticMQ in Docker with the same worker code.

## AWS representation (`infra/terraform/`, validated with `terraform validate`, not applied)

| Resource | Purpose | Least-privilege note |
|----------|---------|----------------------|
| `aws_sqs_queue.eval_jobs` + `aws_sqs_queue.eval_jobs_dlq` with redrive `maxReceiveCount=3` | the path above | server-side encryption on |
| `aws_ecs_task_definition.worker` (Fargate) + `aws_ecs_service` desired count 1 | the worker container | task role: `sqs:ReceiveMessage/DeleteMessage/ChangeMessageVisibility` on the one queue, `ssm:GetParameter` on the named parameters, `logs:PutLogEvents` on its group |
| `aws_ssm_parameter` SecureString: `DATABASE_URL`, `VOGENT_API_KEY`, `BACKEND_URL` | configuration and secrets | values never in Terraform files; injected at apply time via variables marked `sensitive` |
| `aws_cloudwatch_log_group` 14-day retention | logs | Logs Insights query documented: `fields @timestamp, event, job_id | filter evaluation_run_id = "<id>"` |
| `aws_cloudwatch_metric_alarm` on DLQ `ApproximateNumberOfMessagesVisible > 0` | failure visibility | SNS topic optional |

Deploy/teardown: `terraform init && terraform plan -var-file=env.tfvars`, `terraform apply`, `terraform destroy`.
Voice-mode evaluations in AWS would need a browser-capable container image; the design notes this and
keeps the worker in replay mode for the deployed path.

## Explicitly out of scope

Multi-AZ, autoscaling, VPC design beyond defaults, CI/CD pipeline, live apply.
