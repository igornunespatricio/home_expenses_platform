output "bucket_name" {
  description = "Private S3 bucket that holds the original receipt files."
  value       = aws_s3_bucket.receipts.bucket
}

output "function_name" {
  description = "Receipts Lambda function name (for logs)."
  value       = aws_lambda_function.receipts.function_name
}
