variable "name" {
  description = "Name prefix, e.g. expense-tracker-dev."
  type        = string
}

variable "source_dir" {
  description = "Folder with the Lambda code (receipts_handler.py, handler.py, receipt_parser.py)."
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

variable "api_id" {
  description = "ID of the existing HTTP API the receipt routes are added to."
  type        = string
}

variable "api_execution_arn" {
  description = "Execution ARN of that API (invoke permission)."
  type        = string
}

variable "authorizer_id" {
  description = "ID of the existing Cognito JWT authorizer."
  type        = string
}

variable "force_destroy" {
  description = "Allow destroying the bucket while it still holds receipts (dev only)."
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the Lambda."
  type        = number
  default     = 14
}
