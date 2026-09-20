variable "region" {
  description = "AWS region."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names so two environments cannot collide."
  type        = string
  default     = "dev"
}

variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
  default     = "careflow"
}

variable "log_retention_days" {
  description = "How long worker logs are kept. Short by default: the logs carry identifiers, not patient data, and an evaluation run is only interesting while it is recent."
  type        = number
  default     = 14
}

variable "worker_image" {
  description = "Container image for the worker. Built from the repository root Dockerfile, pushed to a registry this account can pull from."
  type        = string
  default     = "careflow/worker:latest"
}

variable "worker_desired_count" {
  description = "How many workers run. One is enough: jobs are independent and the queue serialises them."
  type        = number
  default     = 1
}

variable "subnet_ids" {
  description = "Private subnets for the worker task."
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security groups for the worker task. Egress only; the worker accepts no inbound traffic."
  type        = list(string)
  default     = []
}

# Secrets are never Terraform values. These are the SSM parameter *names* the task
# reads at start; the values are written out of band, so nothing sensitive reaches
# a state file, a plan output, or a pull request diff.
variable "database_url_parameter" {
  description = "SSM SecureString parameter name holding DATABASE_URL."
  type        = string
  default     = "/careflow/dev/database_url"
}

variable "backend_url_parameter" {
  description = "SSM SecureString parameter name holding the evidence API base URL."
  type        = string
  default     = "/careflow/dev/backend_url"
}

variable "function_token_parameter" {
  description = "SSM SecureString parameter name holding the demo practice's function token."
  type        = string
  default     = "/careflow/dev/function_token"
}

# The worker replays scenarios through the evidence API exactly as the local runner
# does, so it needs the same five settings the runner needs. Passing only three was
# enough to plan and validate, and would have failed on the worker's first boot.
variable "webhook_token_parameter" {
  description = "SSM SecureString parameter name holding the demo practice's webhook token."
  type        = string
  default     = "/careflow/dev/webhook_token"
}

variable "organization_id_parameter" {
  description = "SSM SecureString parameter name holding the demo organization id."
  type        = string
  default     = "/careflow/dev/organization_id"
}

variable "alarm_topic_arn" {
  description = "Optional SNS topic for the dead-letter alarm. Empty means the alarm exists but notifies nobody."
  type        = string
  default     = ""
}
