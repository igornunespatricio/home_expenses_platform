variable "name" {
  description = "Name prefix, e.g. expense-tracker-dev."
  type        = string
}

variable "source_dir" {
  description = "Folder with the Lambda code (handler.py)."
  type        = string
}

variable "table_name" {
  description = "DynamoDB table name (passed to the Lambda)."
  type        = string
}

variable "table_arn" {
  description = "DynamoDB table ARN (IAM)."
  type        = string
}

variable "gsi_name" {
  description = "Name of the merchant index (passed to the Lambda)."
  type        = string
}

variable "gsi_arn" {
  description = "ARN of the merchant index (IAM)."
  type        = string
}

variable "issuer_url" {
  description = "Cognito JWT issuer URL."
  type        = string
}

variable "client_id" {
  description = "Cognito app client ID (JWT audience)."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the Lambda."
  type        = number
  default     = 14
}
