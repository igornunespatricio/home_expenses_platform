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

output "user_pool_id" {
  description = "Cognito user pool ID (React app config, admin-create-user)."
  value       = module.auth.user_pool_id
}

output "user_pool_client_id" {
  description = "Cognito app client ID (React app config)."
  value       = module.auth.user_pool_client_id
}

output "cognito_issuer_url" {
  description = "JWT issuer URL used by the API Gateway authorizer."
  value       = module.auth.issuer_url
}

# Added as the next modules are built:
#   cloudfront_domain, bucket_name, distribution_id (frontend)
