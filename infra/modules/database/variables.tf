variable "table_name" {
  description = "DynamoDB table name, e.g. expenses-dev."
  type        = string
}

variable "point_in_time_recovery" {
  description = "Enable point-in-time recovery."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Enable deletion protection on the table."
  type        = bool
  default     = false
}
