output "workspace" {
  description = "Terraform workspace (environment) this state belongs to."
  value       = terraform.workspace
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB expenses table."
  value       = module.database.table_name
}

output "dynamodb_table_arn" {
  description = "ARN of the DynamoDB expenses table."
  value       = module.database.table_arn
}

# Added as the next modules are built:
#   cloudfront_domain, bucket_name, distribution_id (frontend)
#   user_pool_id, user_pool_client_id (auth)
