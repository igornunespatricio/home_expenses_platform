data "aws_caller_identity" "current" {}

locals {
  function_name = "${var.name}-receipts"
  bucket_name   = "${var.name}-receipts-${data.aws_caller_identity.current.account_id}"
}

# ---------- S3 bucket for the original receipt files (private) ----------
resource "aws_s3_bucket" "receipts" {
  bucket        = local.bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# The files hold names and purchase details: refuse any non-TLS access.
data "aws_iam_policy_document" "bucket" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.receipts.arn, "${aws_s3_bucket.receipts.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "receipts" {
  bucket = aws_s3_bucket.receipts.id
  policy = data.aws_iam_policy_document.bucket.json

  depends_on = [aws_s3_bucket_public_access_block.receipts]
}

# ---------- Lambda package ----------
# Same folder as the main API (both handlers live in it), packaged separately so
# the two functions have their own role, settings and deployments.
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/build/${local.function_name}.zip"
  excludes    = ["tests", "__pycache__", ".pytest_cache", "requirements.txt"]
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
}

# ---------- IAM (least privilege) ----------
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "permissions" {
  # Reads the "already imported" row, writes the item rows and the receipt row,
  # and removes rows again if a save fails halfway. No Query/Scan, no index access.
  statement {
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = [var.table_arn]
  }

  # Write-only, and only under receipts/
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.receipts.arn}/receipts/*"]
  }

  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }
}

resource "aws_iam_role" "lambda" {
  name               = local.function_name
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy" "lambda" {
  name   = "access"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.permissions.json
}

# ---------- Lambda ----------
resource "aws_lambda_function" "receipts" {
  function_name = local.function_name
  role          = aws_iam_role.lambda.arn

  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "receipts_handler.lambda_handler"
  timeout       = 15
  memory_size   = 256

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      TABLE_NAME      = var.table_name
      RECEIPTS_BUCKET = aws_s3_bucket.receipts.bucket
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda,
  ]
}

# ---------- Routes on the existing API ----------
# These exact routes win over the main API's "ANY /api/{proxy+}" catch-all.
# Same JWT authorizer, so no valid token means 401 and the Lambda never runs.
resource "aws_apigatewayv2_integration" "receipts" {
  api_id                 = var.api_id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.receipts.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "import" {
  api_id             = var.api_id
  route_key          = "POST /api/receipts/import"
  target             = "integrations/${aws_apigatewayv2_integration.receipts.id}"
  authorization_type = "JWT"
  authorizer_id      = var.authorizer_id
}

resource "aws_apigatewayv2_route" "save" {
  api_id             = var.api_id
  route_key          = "POST /api/receipts"
  target             = "integrations/${aws_apigatewayv2_integration.receipts.id}"
  authorization_type = "JWT"
  authorizer_id      = var.authorizer_id
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.receipts.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${var.api_execution_arn}/*/POST/api/receipts*"
}
