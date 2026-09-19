# Asynchronous evaluation path

Owner of: the queue → worker → persisted result design, how it is demonstrated locally,
and the Terraform that defines the same shape in AWS.

## The shape

```
`make enqueue` or an API call
        │  SendMessage {job_id, scenario_ids, mode, evaluation_run_id}
        ▼
   eval-jobs queue ──(3 failed receives)──▶ eval-jobs-dlq ──▶ CloudWatch alarm
        │
        ▼
   worker (long-poll)  ──▶  evaluation runner (replay)  ──▶  evidence API  ──▶  PostgreSQL
        │
        └── JSON logs carrying job_id, evaluation_run_id, scenario_id
```

One job becomes one persisted `evaluation_runs` row with an `evaluation_cases` row per
scenario. The queue message, the database row and every log line carry the same
identifiers, so a failure can be traced from an alarm to the exact scenario that caused it.

## Why replay only

A voice run needs a browser and a Vogent workspace. A headless container in a private
subnet has neither, and pretending otherwise would produce a worker that fails in
production for a reason that was obvious in advance. The worker rejects any job whose
`mode` is not `replay`, and says so in the rejection.

## Demonstrated locally

```bash
make worker-demo
```

Runs against a local SQS-compatible server. Evidence is written to `artifacts/worker/`.

**A successful job.** Two scenarios replayed, both passed, one `evaluation_runs` row
closed as `completed` with its wall time, two `evaluation_cases` rows recorded.

**A poisoned job.** A job naming a scenario that does not exist. Received three times,
failed identically each time with `reason_code="unknown scenario: Z_does_not_exist"`,
then moved to the dead-letter queue by the redrive policy:

```
dead-letter queue: 1 message(s)
  job_id=job-b709bd5d1b  scenarios=Z_does_not_exist  receives=4
    find the logs with: grep '"job_id": "job-b709bd5d1b"' <worker log>
```

**Finding the logs.** `python -m worker.dlq_inspect` prints the grep for the local log,
and in AWS the equivalent is the Logs Insights query in the Terraform outputs:

```
fields @timestamp, event, job_id, scenario_id, passed
| filter evaluation_run_id = '<run-id>'
| sort @timestamp asc
```

### A bug the demonstration found

The first run showed an empty dead-letter queue. The worker had concluded the queue was
empty while the poisoned message was still invisible after its second failure, so it
never reached a third receive. An empty poll is not an empty queue. The worker now waits
past the visibility timeout before deciding there is no more work. Without running the
demonstration I would have shipped a worker that stops short of the retry it exists to
perform.

## Design decisions worth defending

**Delete only after the run row is closed.** If the worker dies mid-job the message
becomes visible again and is retried. That is at-least-once delivery, stated plainly
rather than claimed as exactly-once. Cases upsert on `(run_id, scenario_id)`, so a retry
updates rather than duplicates.

**A job that can never succeed is not retried differently.** An unknown scenario fails the
same way three times and is dead-lettered. The alternative, failing it immediately and
deleting it, loses the message. Keeping it costs two extra receives and leaves the
evidence somewhere an operator can find it.

**The run row is marked failed on the first failure**, not after the third. An operator
sees the failure immediately instead of a minute later, while the message continues
through its retries independently.

**Two IAM roles, not one.** The execution role starts the task and reads the named SSM
parameters. The task role is what the worker's own code can do: consume from exactly one
queue, read-only on the dead-letter queue, write its own log stream. No `SendMessage` —
this worker consumes jobs and should not be able to enqueue work for itself. Collapsing
the roles is the common shortcut and gives application code the power to read every
secret in the account.

**Secrets are parameter names, never values.** `terraform.tfvars` carries the SSM
SecureString *names*; the values are written out of band. Nothing sensitive reaches
Terraform state, a plan output, or a pull request diff.

## AWS definition

`infra/terraform/`:

| File | What it defines |
|------|-----------------|
| `sqs.tf` | Work queue and dead-letter queue, redrive after 3 receives, SSE, redrive-allow scoped to one source |
| `iam.tf` | Separate execution and task roles, each scoped to named resources |
| `ecs.tf` | Fargate task definition and service; secrets injected from SSM at start |
| `logs.tf` | Log group with retention, and an alarm on the dead-letter queue being non-empty |
| `outputs.tf` | Queue URLs, log group, and the Logs Insights query to trace a run |

Deploy and tear down:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in subnets, image, parameter names
terraform init
terraform plan
terraform apply
terraform destroy      # removes every resource in this stack
```

## Not deployed

No AWS account was used. The definition is written and validated; it has never been
applied, and no claim is made that it works against real AWS beyond what validation
proves. The worker behaviour it describes is demonstrated locally and that evidence is
in `artifacts/worker/`.
