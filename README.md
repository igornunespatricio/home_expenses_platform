# Expense Tracker

Small serverless app to track personal expenses (CRUD), with Cognito login. Everything is provisioned with Terraform; `dev` and `prod` are Terraform **workspaces**, deployed by a CI/CD pipeline.

## Architecture

```
Browser (React) ──► CloudFront ──┬─► S3 (private, via OAC)          static app (default behavior)
        │                        └─► API Gateway (HTTP API)         /api/* behavior
        │                                 │  JWT authorizer
        └── sign in ──► Cognito ◄─────────┘  (validates token)
                                          └─► Lambda (Python) ──► DynamoDB
```

| Layer    | Service                        | Notes                                                    |
|----------|--------------------------------|----------------------------------------------------------|
| Frontend | React (Vite) on S3 + CloudFront | Bucket fully private; CloudFront reads it via OAC        |
| Auth     | Cognito User Pool + app client | Self sign-up disabled (personal use); SRP login via Amplify |
| API      | API Gateway HTTP API + Lambda (Python 3.12) | JWT authorizer on every route                 |
| Database | DynamoDB (on-demand)           | One table per workspace                                  |
| IaC      | Terraform + workspaces         | State in S3 (native locking), one state per workspace    |
| CI/CD    | GitHub Actions (OIDC to AWS)   | No long-lived AWS keys                                   |

The API is served under `/api/*` on the same CloudFront domain, so there is no CORS setup.

## Repo structure

```
.
├── app/                      # React + Vite (aws-amplify for Cognito)
├── api/
│   ├── handler.py            # Lambda entrypoint: routes -> CRUD
│   ├── requirements.txt
│   └── tests/
├── infra/
│   ├── backend.tf            # S3 backend (bucket from bootstrap script)
│   ├── main.tf               # wires modules; config chosen by terraform.workspace
│   ├── variables.tf / outputs.tf
│   ├── envs/
│   │   ├── dev.tfvars
│   │   └── prod.tfvars
│   └── modules/
│       ├── database/         # DynamoDB table + GSI
│       ├── auth/             # Cognito user pool + app client
│       ├── api/              # Lambda, IAM, API Gateway, JWT authorizer
│       └── frontend/         # S3, CloudFront, OAC, bucket policy
├── scripts/
│   └── bootstrap-state.sh    # creates the Terraform state bucket (run once)
└── .github/workflows/
    ├── ci.yml                # PRs: lint, test, build, terraform plan (dev)
    └── cd.yml                # main: deploy dev -> approval -> deploy prod
```

## Data model (DynamoDB)

Table `expenses-<workspace>` (e.g. `expenses-dev`)

| Attribute     | Type | Example                        | Meaning                                      |
|---------------|------|--------------------------------|----------------------------------------------|
| `pk` (hash)   | S    | `USER#<cognito-sub>`           | Owner, taken from the JWT, never from the client |
| `sk` (range)  | S    | `EXP#2026-10-05#<ulid>`        | Date + unique id (sortable, month queries)   |
| `amount`      | N    | `42.90`                        |                                              |
| `date`        | S    | `2026-10-05`                   |                                              |
| `category`    | S    | `supermarket`, `clothing`      | Type of place                                |
| `merchant`    | S    | `guanabara`, `assai`, `nike`   | **Where** the expense happened               |
| `description` | S    | `Weekly groceries`             | Optional                                     |
| `gsi1pk`      | S    | `USER#<sub>#MERCHANT#guanabara`| For "all spending at X"                      |
| `gsi1sk`      | S    | `2026-10-05#<ulid>`            |                                              |

- List a month: `Query pk = USER#<sub> AND begins_with(sk, "EXP#2026-10")`
- Spending at one merchant: `Query` on `gsi1` with `gsi1pk = USER#<sub>#MERCHANT#<merchant>`
- Normalize `category` and `merchant` to lowercase on write so `Nike` and `nike` don't split. The UI can offer a dropdown of previously used merchants, plus "other".

## API

All routes require `Authorization: Bearer <Cognito ID/access token>`. The Lambda reads the user from `event.requestContext.authorizer.jwt.claims.sub`.

| Method | Path                 | Action                                                        |
|--------|----------------------|---------------------------------------------------------------|
| POST   | `/api/expenses`      | Create (`amount`, `date`, `category`, `merchant`, `description`) |
| GET    | `/api/expenses`      | List (`?month=YYYY-MM`, optional `?merchant=nike`)            |
| GET    | `/api/expenses/{id}` | Get one                                                       |
| PUT    | `/api/expenses/{id}` | Update                                                        |
| DELETE | `/api/expenses/{id}` | Delete                                                        |

`{id}` is the `sk` value (URL-encoded). Validate input in the Lambda (amount > 0, valid date, non-empty merchant).

## Terraform

### 1. State bucket (once)

```bash
./scripts/bootstrap-state.sh                 # or: ./scripts/bootstrap-state.sh my-bucket sa-east-1
```

Creates a versioned, encrypted, non-public S3 bucket and prints the name. Put it in `infra/backend.tf`:

```hcl
terraform {
  required_version = ">= 1.10"
  backend "s3" {
    bucket       = "expense-tracker-tfstate-<account-id>"
    key          = "expense-tracker/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true   # native S3 locking, no DynamoDB lock table needed
  }
}
```

Each workspace gets its own state automatically, stored under `env:/<workspace>/expense-tracker/terraform.tfstate`.

### 2. Workspaces = environments

```bash
cd infra
terraform init
terraform workspace new dev     # once
terraform workspace new prod    # once

terraform workspace select dev
terraform apply -var-file=envs/dev.tfvars
```

Rules to keep workspaces safe:
- Every resource name includes `terraform.workspace` (`expenses-dev`, `expense-tracker-api-prod`, ...) so both environments can live in the **same AWS account** without clashing.
- Per-env settings come from `envs/<workspace>.tfvars` (log retention, PITR, deletion protection, etc.). Prod: PITR on, `deletion_protection = true`.
- Always check `terraform workspace show` before applying locally. The pipeline selects the workspace explicitly.

### 3. Module notes

- **database:** `PAY_PER_REQUEST`; hash `pk`, range `sk`; GSI `gsi1` on `gsi1pk`/`gsi1sk`.
- **auth:** `aws_cognito_user_pool` (`allow_admin_create_user_only = true`, email as username, password policy), `aws_cognito_user_pool_client` (no secret, `ALLOW_USER_SRP_AUTH` + `ALLOW_REFRESH_TOKEN_AUTH`). Create your user with `aws cognito-idp admin-create-user`.
- **api:** package `api/` with `archive_file`; least-privilege IAM (`PutItem/GetItem/UpdateItem/DeleteItem/Query` on the table and `gsi1` only); `aws_apigatewayv2_api` (HTTP) + `aws_apigatewayv2_authorizer` type `JWT` with `issuer = https://cognito-idp.<region>.amazonaws.com/<user_pool_id>` and `audience = [<app_client_id>]`; route `ANY /api/{proxy+}` using that authorizer.
- **frontend:** private S3 (`block_public_access` all on), CloudFront OAC, bucket policy allowing only the distribution; `default_root_object = index.html`, 403/404 -> `/index.html` for SPA routing; second origin = API Gateway with `/api/*` behavior, caching disabled, all headers (incl. `Authorization`) forwarded.
- **outputs:** `cloudfront_domain`, `bucket_name`, `distribution_id`, `user_pool_id`, `user_pool_client_id`.

## Frontend (React)

- Vite + React, `aws-amplify` with `<Authenticator>` for login.
- Config injected at build time from Terraform outputs: `VITE_USER_POOL_ID`, `VITE_USER_POOL_CLIENT_ID`, `VITE_AWS_REGION`. API base URL is simply `/api` (same domain).
- Pages: expense list with month filter and total, add/edit form (category, merchant, amount, date), delete, spending by merchant.
- Local dev: `cd app && npm install && npm run dev`, with Vite proxying `/api` to the dev CloudFront domain.

## CI/CD (GitHub Actions)

Authenticates to AWS with OIDC (`aws-actions/configure-aws-credentials`, `role-to-assume`). Create the OIDC provider and deploy role(s) once, manually or in a small separate Terraform stack. Use GitHub Environments `dev` and `prod` (variables: `AWS_ROLE_ARN`, `AWS_REGION`, `TF_STATE_BUCKET`).

**`ci.yml`: on pull request**
1. API: `ruff`, `pytest`
2. App: `npm ci`, `npm run lint`, `npm run build`
3. Terraform: `fmt -check`, `validate`, then `workspace select dev` + `plan -var-file=envs/dev.tfvars`

**`cd.yml`: on push to `main`**
1. **deploy-dev** (Environment `dev`):
   `terraform workspace select -or-create dev` -> `apply -var-file=envs/dev.tfvars -auto-approve` -> read outputs -> `npm run build` with `VITE_*` from outputs -> `aws s3 sync app/dist s3://$BUCKET --delete` -> `aws cloudfront create-invalidation --paths "/*"`
2. **deploy-prod** (Environment `prod`, **required reviewers = manual approval**, `needs: deploy-dev`): same steps with `prod`.

Use `concurrency: terraform-${{ matrix/env }}` so applies never overlap, and protect `main` (PR + passing CI required).

## Getting started

1. **Prereqs:** AWS account + CLI configured, Terraform >= 1.10, Python 3.12, Node 20, GitHub repo.
2. `./scripts/bootstrap-state.sh` and set the bucket in `infra/backend.tf`.
3. `cd infra && terraform init && terraform workspace new dev && terraform workspace new prod`.
4. Deploy dev manually once: `terraform workspace select dev && terraform apply -var-file=envs/dev.tfvars`.
5. Create your Cognito user:
   ```bash
   aws cognito-idp admin-create-user --user-pool-id <id> --username you@example.com \
     --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
   ```
6. Create the GitHub OIDC role + Environments, push to `main`, and let the pipeline deploy dev -> prod.

## Suggested build order

1. `database` module -> table + GSI
2. `auth` module -> user pool, test user
3. `api` module + `handler.py` -> test with `curl` and a real Cognito token (also confirm a call without a token returns 401)
4. `frontend` module -> hello-world `index.html`; confirm the bucket is private and the site only loads via CloudFront
5. `/api/*` behavior in CloudFront
6. React UI with login + CRUD
7. CI/CD workflows
8. Later: custom domain (Route 53 + ACM in `us-east-1`), budgets/alarms

## Rough cost

All pay-per-use; a personal tracker should cost cents per month (Cognito is free under 10k MAU), excluding a custom domain.