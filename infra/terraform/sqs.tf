# The work queue and its dead-letter queue.
#
# This is the same shape the local demo runs against (`make worker-demo`): a job that
# fails three times stops being retried and lands somewhere an engineer can inspect it,
# rather than looping forever and burning the worker on a job that can never succeed.

resource "aws_sqs_queue" "eval_jobs_dlq" {
  name = "${var.name_prefix}-${var.environment}-eval-jobs-dlq"

  # Poisoned jobs are kept long enough that a failure over a weekend is still there
  # on Monday.
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "eval_jobs" {
  name = "${var.name_prefix}-${var.environment}-eval-jobs"

  # Must exceed the longest job or a slow run is handed to a second worker and done
  # twice. Evaluation runs are idempotent per (run, scenario), so a duplicate updates
  # rather than corrupts, but paying for the work twice is still waste.
  visibility_timeout_seconds = 300
  message_retention_seconds  = 345600 # 4 days
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.eval_jobs_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.eval_jobs_dlq.id

  # Only this queue may redrive into the dead-letter queue.
  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.eval_jobs.arn]
  })
}
