#!/usr/bin/env bash
# Creates the S3 bucket that stores Terraform state for ALL workspaces (dev + prod).
# Run once, before the first `terraform init`. Safe to re-run (idempotent).
#
# Usage: ./scripts/bootstrap-state.sh [bucket-name] [region]
#   bucket-name  default: expense-tracker-tfstate-<aws-account-id>
#   region       default: us-east-1
set -euo pipefail

REGION="${2:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${1:-expense-tracker-tfstate-${ACCOUNT_ID}}"

echo "Bucket: ${BUCKET}  Region: ${REGION}"

if aws s3api head-bucket --bucket "${BUCKET}" 2>/dev/null; then
  echo "Bucket already exists, re-applying settings."
else
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
fi

# Encrypt at rest
aws s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# Never public
aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo
echo "Done. Use this in infra/backend.tf:"
echo "  bucket = \"${BUCKET}\""
echo "  region = \"${REGION}\""