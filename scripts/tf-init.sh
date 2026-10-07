#!/usr/bin/env bash
# Initializes Terraform (S3 backend), creates the dev and prod workspaces if
# missing, and selects the one you ask for. Safe to re-run.
#
# Usage:  bash scripts/tf-init.sh [dev|prod]      (default: dev)
#
# Config is read from the GitHub environment variables for the chosen workspace
# (AWS_REGION and TF_STATE_BUCKET, set by scripts/oidc-setup.sh) via the gh CLI.
# Optional env vars (take precedence over GitHub if exported in your shell):
#   AWS_REGION       region of the state bucket
#   TF_STATE_BUCKET  name of the state bucket
#   TF_INIT_ARGS     extra args for `terraform init`, e.g. "-reconfigure"
set -euo pipefail

# Print where and why the script failed before exiting
trap 'echo "ERROR: command failed (exit $?) at line $LINENO: $BASH_COMMAND" >&2' ERR

# Guard: execute this script, do not source it
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  echo "Run this script with: bash scripts/tf-init.sh (do not 'source' it)" >&2
  return 1
fi

WORKSPACE="${1:-dev}"
case "$WORKSPACE" in
  dev|prod) ;;
  *) echo "Error: workspace must be 'dev' or 'prod' (got '${WORKSPACE}')" >&2; exit 1 ;;
esac

for cmd in terraform gh; do
  command -v "$cmd" >/dev/null || { echo "Error: '$cmd' not found in PATH" >&2; exit 1; }
done

# Run from the infra folder regardless of where the script was called from
# (also keeps gh inside the repo so it can detect it)
cd "$(dirname "${BASH_SOURCE[0]}")/../infra"

# Read a config value: exported shell variable first, then the GitHub
# environment variable of the same name for the chosen workspace.
get_var() {
  local name="$1" value="${!1:-}"
  if [ -z "$value" ]; then
    value="$(gh variable get "$name" --env "$WORKSPACE" 2>/dev/null || true)"
  fi
  if [ -z "$value" ]; then
    echo "Error: '${name}' is not set in your shell or in the GitHub '${WORKSPACE}' environment." >&2
    echo "       Run scripts/oidc-setup.sh to create it, or 'gh auth login' if gh is not logged in." >&2
    exit 1
  fi
  printf '%s' "$value"
}

AWS_REGION="$(get_var AWS_REGION)"
TF_STATE_BUCKET="$(get_var TF_STATE_BUCKET)"

echo "Bucket:    ${TF_STATE_BUCKET}"
echo "Region:    ${AWS_REGION}"
echo "Workspace: ${WORKSPACE}"
echo

echo "Step 1: terraform init..."
# shellcheck disable=SC2086
terraform init -input=false ${TF_INIT_ARGS:-} \
  -backend-config="bucket=${TF_STATE_BUCKET}" \
  -backend-config="region=${AWS_REGION}"

echo "Step 2: ensuring workspaces exist..."
for ws in dev prod; do
  terraform workspace select -or-create "$ws" >/dev/null
  echo "  ${ws}: ok"
done

echo "Step 3: selecting workspace '${WORKSPACE}'..."
terraform workspace select "$WORKSPACE"

echo
echo "Done. Current workspace: $(terraform workspace show)"
echo "Next: cd infra && terraform plan -var-file=envs/${WORKSPACE}.tfvars"