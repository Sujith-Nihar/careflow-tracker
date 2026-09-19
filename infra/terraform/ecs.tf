resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name_prefix}-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = var.worker_image
      essential = true
      command   = ["python", "-m", "worker.main"]

      environment = [
        { name = "AWS_REGION", value = var.region },
        { name = "EVAL_QUEUE_NAME", value = aws_sqs_queue.eval_jobs.name },
        { name = "EVAL_DLQ_NAME", value = aws_sqs_queue.eval_jobs_dlq.name },
        # Must stay below the queue's visibility timeout.
        { name = "EVAL_VISIBILITY_TIMEOUT", value = "240" },
        { name = "EVAL_WAIT_SECONDS", value = "20" },
        { name = "LOG_LEVEL", value = "INFO" },
      ]

      # Injected at task start from SSM. Never in the image, never in an environment
      # variable in this file, never in Terraform state.
      secrets = [
        { name = "DATABASE_URL", valueFrom = var.database_url_parameter },
        { name = "BACKEND_URL", valueFrom = var.backend_url_parameter },
        { name = "CAREFLOW_DEMO_ORG_FUNCTION_TOKEN", valueFrom = var.function_token_parameter },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.worker.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "worker"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "worker" {
  name            = "${var.name_prefix}-${var.environment}-worker"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets = var.subnet_ids
    # Private subnets with a NAT route. The worker makes outbound calls to the
    # evidence API and the database; nothing needs to reach it.
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}
