output "bucket_name" {
  description = "S3 bucket that holds the built React app."
  value       = aws_s3_bucket.app.bucket
}

output "distribution_id" {
  description = "CloudFront distribution ID (cache invalidation)."
  value       = aws_cloudfront_distribution.this.id
}

output "distribution_arn" {
  description = "CloudFront distribution ARN."
  value       = aws_cloudfront_distribution.this.arn
}

output "cloudfront_domain" {
  description = "Site domain, e.g. d111111abcdef8.cloudfront.net"
  value       = aws_cloudfront_distribution.this.domain_name
}
