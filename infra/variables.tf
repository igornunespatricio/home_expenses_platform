variable "aws_region" {
  description = "AWS region where the resources are deployed."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name, used as a prefix for resource names and in tags."
  type        = string
  default     = "expense-tracker"
}

variable "point_in_time_recovery" {
  description = "Enable DynamoDB point-in-time recovery (set in envs/<workspace>.tfvars)."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Enable DynamoDB deletion protection (set in envs/<workspace>.tfvars)."
  type        = bool
  default     = false
}
