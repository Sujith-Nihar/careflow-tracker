# Two roles, deliberately separated.
#
# The execution role is what ECS itself uses to start the task: pull the image, read
# the secrets it injects, write the log stream. The task role is what the worker's own
# code can do once running. Collapsing them into one is the common shortcut and it
# means application code inherits the power to read every secret in the account.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# ---------------------------------------------------------------- execution role
resource "aws_iam_role" "execution" {
  name               = "${var.name_prefix}-${var.environment}-worker-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "execution_secrets" {
  # Named parameters only. Not /careflow/*, and certainly not ssm:GetParameter on "*",
  # so a mistake in this stack cannot read another service's credentials.
  statement {
    actions = ["ssm:GetParameters"]
    resources = [
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${var.database_url_parameter}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${var.backend_url_parameter}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${var.function_token_parameter}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${var.webhook_token_parameter}",
      "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${var.organization_id_parameter}",
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  name   = "read-named-parameters"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution_secrets.json
}

# --------------------------------------------------------------------- task role
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-${var.environment}-worker-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "task_queue" {
  # Exactly what a consumer needs on exactly one queue. No SendMessage: this worker
  # consumes jobs, it does not create them, and a compromised worker should not be
  # able to enqueue work for itself.
  statement {
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
    ]
    resources = [aws_sqs_queue.eval_jobs.arn]
  }

  # Read-only on the dead-letter queue, so an operator can inspect it from the same
  # task without being able to delete the evidence of a failure.
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl"]
    resources = [aws_sqs_queue.eval_jobs_dlq.arn]
  }

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "task_queue" {
  name   = "consume-eval-queue"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_queue.json
}

data "aws_caller_identity" "current" {}
