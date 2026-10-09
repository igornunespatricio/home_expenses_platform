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

output "api_endpoint" {
  description = "Direct API Gateway URL (for curl tests; the app uses CloudFront /api/*)."
  value       = module.api.api_endpoint
}

output "api_domain" {
  description = "API Gateway host, used as the CloudFront origin."
  value       = module.api.api_domain
}

output "lambda_function_name" {
  description = "Lambda function name (for logs)."
  value       = module.api.function_name
}

output "cloudfront_domain" {
  description = "Site domain (the app and /api/* are both served from here)."
  value       = module.frontend.cloudfront_domain
}

output "bucket_name" {
  description = "S3 bucket for the built React app."
  value       = module.frontend.bucket_name
}

output "distribution_id" {
  description = "CloudFront distribution ID (cache invalidation after deploys)."
  value       = module.frontend.distribution_id
}
