output "queue_url" {
  description = "Where to send evaluation jobs."
  value       = aws_sqs_queue.eval_jobs.id
}

output "dead_letter_queue_url" {
  description = "Where poisoned jobs land. Inspect with `python -m worker.dlq_inspect`."
  value       = aws_sqs_queue.eval_jobs_dlq.id
}

output "log_group" {
  description = "Worker logs."
  value       = aws_cloudwatch_log_group.worker.name
}

output "logs_insights_query" {
  description = "Find every line for one evaluation run."
  value       = "fields @timestamp, event, job_id, scenario_id, passed | filter evaluation_run_id = '<run-id>' | sort @timestamp asc"
}
