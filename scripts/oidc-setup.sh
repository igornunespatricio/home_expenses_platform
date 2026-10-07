#!/usr/bin/env bash
# Creates the GitHub OIDC provider and an IAM role so GitHub Actions can
# authenticate to AWS without long-lived credentials.
# Run once from inside the cloned repo. Safe to re-run (idempotent).
#
# Prerequisites:
#   - GitHub CLI (gh) installed and authenticated, run from inside the repo
#   - AWS CLI (aws) configured with IAM admin-level credentials
#
# Optional env vars:
#   AWS_REGION   default: us-east-1
#   POLICY_ARN   managed policy attached to the role
#                default: AdministratorAccess (see warning below)
set -euo pipefail

# Print where and why the script failed before exiting
trap 'echo "ERROR: command failed (exit $?) at line $LINENO: $BASH_COMMAND" >&2' ERR

# Guard: this script must be executed, not sourced (sourcing + set -e closes your shell)
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  echo "Run this script with: bash scripts/oidc-setup.sh (do not 'source' it)" >&2
  return 1
fi

for cmd in gh aws; do
  command -v "$cmd" >/dev/null || { echo "Error: '$cmd' not found in PATH" >&2; exit 1; }
done

# --- Configuration (nothing hardcoded: derived from the current repo) -------
GITHUB_REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"   # owner/repo
REPO_NAME="${GITHUB_REPO#*/}"                                            # repo
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
AWS_REGION="${AWS_REGION:-us-east-1}"

OIDC_HOST="token.actions.githubusercontent.com"
OIDC_PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_HOST}"
IAM_ROLE_NAME="${REPO_NAME}-github-actions"
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${IAM_ROLE_NAME}"

# WARNING: Terraform here creates IAM roles, Lambda, API Gateway, Cognito,
# CloudFront, S3 and DynamoDB, so a narrow policy like S3FullAccess is not enough.
# AdministratorAccess is the simple default for a personal project; tighten it later.
POLICY_ARN="${POLICY_ARN:-arn:aws:iam::aws:policy/AdministratorAccess}"

echo "Repo:    ${GITHUB_REPO}"
echo "Account: ${ACCOUNT_ID}"
echo "Role:    ${IAM_ROLE_NAME}"
echo

# --- Step 1: GitHub OIDC identity provider (one per AWS account) ------------
echo "Step 1: Ensuring GitHub OIDC provider exists..."
if aws iam get-open-id-connect-provider \
     --open-id-connect-provider-arn "$OIDC_PROVIDER_ARN" >/dev/null 2>&1; then
  echo "  Provider already exists."
else
  aws iam create-open-id-connect-provider \
    --url "https://${OIDC_HOST}" \
    --client-id-list sts.amazonaws.com >/dev/null
  echo "  Provider created."
fi

# --- Step 2: IAM role trusted only by THIS repo -----------------------------
echo "Step 2: Ensuring IAM role exists..."
TRUST_POLICY="$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Federated": "${OIDC_PROVIDER_ARN}" },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": { "${OIDC_HOST}:aud": "sts.amazonaws.com" },
        "StringLike": {
          "${OIDC_HOST}:sub": [
            "repo:${GITHUB_REPO}:environment:dev",
            "repo:${GITHUB_REPO}:environment:prod",
            "repo:${GITHUB_REPO}:pull_request"
          ]
        }
      }
    }
  ]
}
EOF
)"

if aws iam get-role --role-name "$IAM_ROLE_NAME" >/dev/null 2>&1; then
  aws iam update-assume-role-policy \
    --role-name "$IAM_ROLE_NAME" \
    --policy-document "$TRUST_POLICY"
  echo "  Role already exists, trust policy updated."
else
  aws iam create-role \
    --role-name "$IAM_ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" >/dev/null
  echo "  Role created."
fi

aws iam attach-role-policy --role-name "$IAM_ROLE_NAME" --policy-arn "$POLICY_ARN"
echo "  Attached policy: ${POLICY_ARN}"

# --- Step 3: Verify ----------------------------------------------------------
echo "Step 3: Verifying..."
aws iam get-role --role-name "$IAM_ROLE_NAME" --query Role.Arn --output text

# --- Step 4: GitHub environments + variables --------------------------------
echo "Step 4: Configuring GitHub environments and variables..."
TF_STATE_BUCKET="expense-tracker-tfstate-${ACCOUNT_ID}"   # same default as bootstrap-state.sh

for ENV in dev prod; do
  gh api -X PUT "repos/${GITHUB_REPO}/environments/${ENV}" >/dev/null
  gh variable set AWS_ROLE_ARN    --env "$ENV" --body "$ROLE_ARN"
  gh variable set AWS_REGION      --env "$ENV" --body "$AWS_REGION"
  gh variable set TF_STATE_BUCKET --env "$ENV" --body "$TF_STATE_BUCKET"
  echo "  [${ENV}] environment created and variables set."
done

# Approval gate on prod: make the current GitHub user a required reviewer.
# Best effort: private repos on the free GitHub plan don't support this.
USER_ID="$(gh api user --jq .id)"
if echo "{\"reviewers\":[{\"type\":\"User\",\"id\":${USER_ID}}]}" \
     | gh api -X PUT "repos/${GITHUB_REPO}/environments/prod" --input - >/dev/null 2>&1; then
  echo "  [prod] required reviewer set (you)."
else
  echo "  [prod] WARNING: could not set required reviewers (private repos need GitHub Pro/Team)."
  echo "         Set it manually: https://github.com/${GITHUB_REPO}/settings/environments"
fi

# --- Summary -----------------------------------------------------------------
cat <<EOF

==========================================
OIDC setup complete
==========================================
Repo:      ${GITHUB_REPO}
Provider:  ${OIDC_PROVIDER_ARN}
Role ARN:  ${ROLE_ARN}

GitHub environments 'dev' and 'prod' are configured with variables:
  AWS_ROLE_ARN    = ${ROLE_ARN}
  AWS_REGION      = ${AWS_REGION}
  TF_STATE_BUCKET = ${TF_STATE_BUCKET}

Workflows need:  permissions: { id-token: write, contents: read }
EOF