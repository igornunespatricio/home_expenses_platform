output "user_pool_id" {
  description = "Cognito user pool ID."
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  description = "Cognito user pool ARN."
  value       = aws_cognito_user_pool.this.arn
}

output "user_pool_client_id" {
  description = "App client ID (JWT authorizer audience and React app config)."
  value       = aws_cognito_user_pool_client.app.id
}

output "issuer_url" {
  description = "JWT issuer URL for the API Gateway authorizer."
  value       = "https://cognito-idp.${data.aws_region.current.region}.amazonaws.com/${aws_cognito_user_pool.this.id}"
}
