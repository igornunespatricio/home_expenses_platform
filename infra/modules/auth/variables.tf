variable "name" {
  description = "Name prefix for the user pool, e.g. expense-tracker-dev."
  type        = string
}

variable "deletion_protection" {
  description = "Protect the user pool from deletion (users would be lost)."
  type        = bool
  default     = false
}
