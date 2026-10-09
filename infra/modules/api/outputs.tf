output "api_id" {
  description = "API Gateway ID."
  value       = aws_apigatewayv2_api.this.id
}

output "api_endpoint" {
  description = "Full API URL, e.g. https://abc123.execute-api.us-east-1.amazonaws.com"
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_domain" {
  description = "API host without https:// (CloudFront origin domain)."
  value       = replace(aws_apigatewayv2_api.this.api_endpoint, "https://", "")
}

output "function_name" {
  description = "Lambda function name."
  value       = aws_lambda_function.api.function_name
}
