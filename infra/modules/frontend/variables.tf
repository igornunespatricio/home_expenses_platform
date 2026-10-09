variable "name" {
  description = "Name prefix, e.g. expense-tracker-dev."
  type        = string
}

variable "api_domain" {
  description = "API Gateway host without https:// (origin for /api/*)."
  type        = string
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete the bucket even if it has files."
  type        = bool
  default     = false
}
