resource "aws_cloudwatch_log_group" "worker" {
  name              = "/${var.name_prefix}/${var.environment}/worker"
  retention_in_days = var.log_retention_days
}

# A job that lands in the dead-letter queue means an evaluation stopped producing
# results. Nobody watches a queue depth graph, so this is the thing that pages.
resource "aws_cloudwatch_metric_alarm" "dead_letter_not_empty" {
  alarm_name          = "${var.name_prefix}-${var.environment}-eval-dlq-not-empty"
  alarm_description   = "An evaluation job failed three times and was dead-lettered. Run `python -m worker.dlq_inspect` and grep the worker log for its job_id."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.eval_jobs_dlq.name
  }

  alarm_actions = var.alarm_topic_arn == "" ? [] : [var.alarm_topic_arn]
}
