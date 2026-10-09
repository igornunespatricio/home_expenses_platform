data "aws_caller_identity" "current" {}

locals {
  bucket_name = "${var.name}-frontend-${data.aws_caller_identity.current.account_id}"

  # AWS managed policies (fixed IDs)
  cache_policy_optimized = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized
  cache_policy_disabled  = "4135ea2d-6df8-43a0-922d-4cd69a8b4a9a" # CachingDisabled
  origin_request_policy  = "b689b0a8-53d0-40ab-baf2-68738e2966ac" # AllViewerExceptHostHeader
  response_headers       = "67f7725c-6f97-4210-82d7-5512b31e9d03" # SecurityHeadersPolicy
}

# ---------- S3 bucket (private) ----------
resource "aws_s3_bucket" "app" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket = aws_s3_bucket.app.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "app" {
  bucket = aws_s3_bucket.app.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ---------- CloudFront ----------
resource "aws_cloudfront_origin_access_control" "app" {
  name                              = "${var.name}-frontend"
  description                       = "CloudFront access to the private app bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# SPA routing: URLs without a file extension (/expenses, /login) serve index.html.
# Done with a function on the default behavior only, because a distribution-wide
# custom error response would also rewrite the API's 403/404 answers.
resource "aws_cloudfront_function" "spa_rewrite" {
  name    = "${var.name}-spa-rewrite"
  runtime = "cloudfront-js-2.0"
  publish = true
  comment = "Serve index.html for client-side routes"

  code = <<-JS
    function handler(event) {
      var request = event.request;
      if (request.uri.indexOf('.') === -1) {
        request.uri = '/index.html';
      }
      return request;
    }
  JS
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  is_ipv6_enabled     = true
  http_version        = "http2and3"
  price_class         = "PriceClass_100"
  default_root_object = "index.html"
  comment             = var.name

  # Origin 1: private S3 bucket (static app)
  origin {
    origin_id                = "app"
    domain_name              = aws_s3_bucket.app.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.app.id
  }

  # Origin 2: API Gateway
  origin {
    origin_id   = "api"
    domain_name = var.api_domain

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # /api/* -> API Gateway (no caching, all viewer headers incl. Authorization, except Host)
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = local.cache_policy_disabled
    origin_request_policy_id = local.origin_request_policy
  }

  # Everything else -> the app in S3
  default_cache_behavior {
    target_origin_id           = "app"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD", "OPTIONS"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cache_policy_optimized
    response_headers_policy_id = local.response_headers

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa_rewrite.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# ---------- Bucket policy: only this distribution can read ----------
data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "AllowCloudFrontRead"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.app.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "app" {
  bucket = aws_s3_bucket.app.id
  policy = data.aws_iam_policy_document.bucket.json

  depends_on = [aws_s3_bucket_public_access_block.app]
}
