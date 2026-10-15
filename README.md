# Home Expenses Platform

A small serverless app to track personal expenses, with login. React app, Python API, DynamoDB, all on AWS and provisioned with Terraform. `dev` and `prod` are Terraform workspaces, deployed by GitHub Actions.

## Architecture

```
Browser (React) ──► CloudFront ──┬─► S3 (private, via OAC)     default behavior: the app
        │                        └─► API Gateway (HTTP API)    /api/* behavior
        │                                 │ JWT authorizer
        └── sign in ──► Cognito ◄─────────┘ (checks the token)
                                          └─► Lambda (Python) ──► DynamoDB
```

| Layer    | Service                                   | Notes                                                       |
|----------|-------------------------------------------|-------------------------------------------------------------|
| Frontend | React (Vite) on S3 + CloudFront           | Bucket is private; only CloudFront reads it (OAC)          |
| Auth     | Cognito user pool                         | No self sign-up: you create users. SRP login via Amplify    |
| API      | API Gateway HTTP API + Lambda (Python 3.12, arm64) | JWT authorizer on every route; throttled to 10 req/s |
| Database | DynamoDB, on-demand                       | One table per environment                                   |
| IaC      | Terraform + workspaces                    | State in S3 with native locking                             |
| CI/CD    | GitHub Actions, OIDC to AWS               | No stored AWS keys                                          |

The API is served under `/api/*` on the same CloudFront domain, so there is no CORS setup. Client-side routes (URLs without a file extension) are answered with `index.html` by a CloudFront Function on the app behavior only, so the API keeps its real 404s.

## Repo structure

```
.
├── app/                         React + Vite + aws-amplify
│   ├── src/                     main, App, Tracker, ExpenseForm, api, config, format, styles
│   ├── .env.example             copy to .env.local for local dev
│   └── package.json / package-lock.json / vite.config.js / eslint.config.js / index.html
├── api/
│   ├── handler.py               Lambda: expense CRUD routes
│   ├── receipts_handler.py      Lambda: import a receipt page (/api/receipts/*)
│   ├── receipt_parser.py        NFC-e (.mht/.html) parser, standard library only
│   ├── tests/                   pytest: handlers, parser, synthetic receipt fixtures
│   └── requirements.txt         dev only (Lambda already ships boto3)
├── infra/
│   ├── backend.tf               S3 backend (bucket passed at init, not hardcoded)
│   ├── main.tf                  provider, workspace guard, wires the modules
│   ├── variables.tf / outputs.tf
│   ├── envs/dev.tfvars, prod.tfvars
│   └── modules/
│       ├── database/            DynamoDB table + merchant index
│       ├── auth/                Cognito user pool + app client
│       ├── api/                 Lambda, IAM, API Gateway, JWT authorizer
│       ├── receipts/            second Lambda + its routes, private S3 bucket for the original receipt files
│       └── frontend/            S3, CloudFront, OAC, SPA routing function
├── scripts/
│   ├── bootstrap-state.sh       creates the Terraform state bucket
│   ├── oidc-setup.sh            GitHub OIDC provider, IAM role, GitHub environments + variables
│   └── tf-init.sh               terraform init + workspaces, config read from GitHub variables
└── .github/workflows/
    ├── ci.yml                   pull requests: lint, test, build, plan dev
    ├── cd.yml                   push to main: dev, then prod after approval
    └── deploy.yml               reusable deploy used by cd.yml
```

## Data model (DynamoDB)

Table `expenses-<env>`, for example `expenses-dev`.

| Attribute     | Example                          | Meaning                                           |
|---------------|----------------------------------|---------------------------------------------------|
| `pk`          | `USER#<cognito-sub>`             | Owner. Always taken from the JWT, never the client |
| `sk`          | `EXP#2026-10-05#<uuid>`          | Date + id. This is the expense `id` the API returns |
| `amount`      | `42.90`                          |                                                   |
| `date`        | `2026-10-05`                     |                                                   |
| `category`    | `supermarket`, `clothing`        | Type of place                                     |
| `merchant`    | `guanabara`, `assai`, `nike`     | Where the expense happened                        |
| `description` | `Weekly groceries`               | Optional                                          |
| `gsi1pk`      | `USER#<sub>#MERCHANT#guanabara`  | Index key: all spending at one merchant           |
| `gsi1sk`      | `2026-10-05#<uuid>`              |                                                   |

`category` and `merchant` are stored in lowercase so `Nike` and `nike` don't split.

### Imported receipts

A receipt imported from an NFC-e page becomes **one expense row per item** (same shape as above, so lists, filters and totals work unchanged) plus one `RECEIPT#` row:

| Row | Key | Extra attributes |
|-----|-----|------------------|
| Item | `sk = EXP#<date>#<access key>-<line>` | `kind` (`product` or `discount`), `line`, `code`, `quantity`, `unit`, `unit_price`, `receipt_key`; `description` is the item name |
| Receipt | `sk = RECEIPT#<access key>` | issuer name and CNPJ, number, series, `issued_at`, `subtotal`, `discount`, `total_paid`, `payments`, `change`, `item_count`, `s3_key`, `imported_at` |

A receipt-level discount is saved as an extra item with a **negative** `amount`, so item prices stay as printed and the rows add up to what was paid. The `RECEIPT#` row is written last and marks the receipt as imported (importing it again returns 409). The original file is kept in a private S3 bucket at `receipts/<user>/<access key>.mht`, with CPF numbers masked.

## API

All routes need `Authorization: Bearer <Cognito ID token>`. Without a valid token API Gateway answers 401 and the Lambda never runs.

| Method | Path                 | Action                                                   |
|--------|----------------------|----------------------------------------------------------|
| POST   | `/api/expenses`      | Create (`amount`, `date`, `category`, `merchant`, `description`) |
| GET    | `/api/expenses`      | List (`?month=YYYY-MM`, optional `?merchant=nike`), newest first |
| GET    | `/api/expenses/{id}` | Get one                                                  |
| PUT    | `/api/expenses/{id}` | Update                                                   |
| DELETE | `/api/expenses/{id}` | Delete                                                   |

Receipt import (needs the same token; the file is the saved NFC-e page as base64):

| Method | Path                    | Action                                                                 |
|--------|-------------------------|------------------------------------------------------------------------|
| POST   | `/api/receipts/import`  | Parse the file and return a draft for review. Writes nothing; 409 if already imported, 422 if unreadable |
| POST   | `/api/receipts`         | Save the reviewed receipt: original file to S3, one expense row per item, then the `RECEIPT#` row |

The save request is `{"file": "<base64>", "receipt": {"merchant", "category", "date", "items": [...]}}`. The access key always comes from the file, never from the client. Receipts come from RJ's NFC-e portal (`consultadfe.fazenda.rj.gov.br`) saved as `.mht` or `.html`; other states use different pages and are rejected.

`{id}` is the URL-encoded `sk`. Input is validated (amount > 0, valid date, merchant and category required) and errors come back as `{"error": "..."}`. Changing an expense's date changes its `id`, because the date is part of the key: the response carries the new one.

## First-time setup

Prerequisites: AWS CLI with admin credentials, GitHub CLI (`gh`) logged in, Terraform >= 1.10, Node 20, Python 3.12. Run everything from the repo root in a bash shell, and always **execute** the scripts (`bash scripts/x.sh`), never `source` them.

1. **State bucket** (once per AWS account):
   ```bash
   bash scripts/bootstrap-state.sh          # bucket: expense-tracker-tfstate-<account-id>, region us-east-1
   ```
2. **GitHub OIDC role and environments** (once). Creates the AWS role, then the `dev` and `prod` GitHub environments with the variables `AWS_ROLE_ARN`, `AWS_REGION`, `TF_STATE_BUCKET`:
   ```bash
   bash scripts/oidc-setup.sh
   ```
   The role gets `AdministratorAccess` by default (override with `POLICY_ARN=...`). It trusts only this repo's `dev` and `prod` environments. The script also makes you the required reviewer on `prod` and limits `prod` deployments to the `main` branch. Re-running it is safe and updates the existing role.
3. **Terraform init and workspaces**. Reads the bucket and region from the GitHub variables:
   ```bash
   bash scripts/tf-init.sh dev              # or: prod
   ```
4. **Deploy dev by hand once:**
   ```bash
   cd infra
   terraform workspace show                 # must print: dev
   terraform apply -var-file=envs/dev.tfvars
   ```
   The first CloudFront deploy takes several minutes.
5. **Create your login** in each environment (use the right workspace first):
   ```bash
   aws cognito-idp admin-create-user \
     --user-pool-id "$(terraform output -raw user_pool_id)" \
     --username you@example.com \
     --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true
   ```
   Cognito emails a temporary password; the app asks for a new one on first login.
6. **Check the API is locked** (should print 401):
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" "$(terraform output -raw api_endpoint)/api/expenses"
   ```

## Terraform

- **Workspaces are the environments.** Every name includes the workspace (`expenses-dev`, `expense-tracker-prod-api`, ...), so both fit in one AWS account. A guard in `main.tf` fails the plan in any workspace other than `dev` or `prod`.
- **Per-environment settings** are in `envs/<workspace>.tfvars`. Prod has point-in-time recovery and deletion protection on, which also blocks `terraform destroy` until you turn them off. Dev bucket and table can be destroyed freely.
- **State:** `backend.tf` holds only the fixed settings. The bucket and region are passed at init (`scripts/tf-init.sh` does this), because Terraform does not allow variables in a backend block. If you change them later, run `TF_INIT_ARGS="-reconfigure" bash scripts/tf-init.sh`.
- **Day to day:**
  ```bash
  cd infra
  terraform workspace select dev
  terraform plan  -var-file=envs/dev.tfvars
  terraform apply -var-file=envs/dev.tfvars
  ```
- **Outputs:** `cloudfront_domain`, `bucket_name`, `distribution_id`, `user_pool_id`, `user_pool_client_id`, `cognito_issuer_url`, `api_endpoint`, `api_domain`, `lambda_function_name`, `dynamodb_table_name`, `dynamodb_table_arn`.

## App (React)

- Login with Cognito, then a month view: total, spending by merchant (click a merchant to filter), expenses grouped by day, add / edit / delete.
- **Import receipt:** pick a saved NFC-e page (`.mht`; in Chrome or Edge press Ctrl+S on the receipt and choose "Webpage, Single File"). The server reads it, you review and edit the merchant, date, category and every item (name, quantity, unit price, total; a discount is a negative line), then save. One expense is created per item.
- Display is in English with amounts in BRL. Change the two constants at the top of `app/src/format.js` for another currency or locale.
- Build-time config: `VITE_USER_POOL_ID` and `VITE_USER_POOL_CLIENT_ID` (Terraform outputs). The pipeline sets them; locally use `app/.env.local`.
- Run locally against the deployed dev stack:
  ```bash
  cd app
  cp .env.example .env.local      # fill in the three values from `terraform output`
  npm install
  npm run dev
  ```
  `VITE_DEV_PROXY_TARGET` (`https://<cloudfront_domain>`) makes Vite forward `/api/*` to dev.

## CI/CD (GitHub Actions)

Workflows log in to AWS with OIDC, using the per-environment variables created by `oidc-setup.sh`.

- **`ci.yml`, on pull requests into `main`:** API `ruff` and `pytest` (skipped until `api/tests` exists); app `npm ci`, lint, build; Terraform format check, validate, and a read-only plan for dev (shown in the job log). This job runs in the `dev` environment, which is where the variables live and which the AWS role trusts.
- **`cd.yml`, on push to `main`:** calls `deploy.yml` for `dev`, then for `prod` (`needs: dev`). Prod waits for approval if required reviewers are set on the `prod` environment. Pushes that only change `.md` files do not deploy. It can also be run manually.
- **`deploy.yml`:** select workspace -> `terraform apply` -> read outputs -> build the app with them -> upload to S3 (hashed assets cached for a year, `index.html` never cached) -> invalidate CloudFront. One deploy per environment at a time.

Recommended: protect `main` (pull request and passing CI required). Required reviewers on `prod` are free on public repos; on private repos they need GitHub Enterprise. `oidc-setup.sh` warns if it could not set them, in which case `prod` deploys right after `dev` with no approval.

### Public repository notes

- Workflow logs are public. They contain no secrets, but they do show resource names, which include the AWS account ID.
- In Settings -> Actions -> General, set "Approval for running fork pull request workflows" to "Require approval for all external contributors". Fork pull requests cannot get AWS credentials anyway.
- Leave "Prevent self-review" off on the `prod` environment, or you cannot approve your own deploys.

## Next steps

1. Receipts from other states (each portal has its own page layout), and a photo/screenshot import for receipts without a saved page.
2. A least-privilege policy for the deploy role instead of `AdministratorAccess`.
3. Custom domain (Route 53 + ACM certificate in `us-east-1`).
4. Budget alert and Lambda error alarm.

## Cost

Everything is pay per use. A personal tracker should cost cents per month: Cognito is free under 10k monthly users, and DynamoDB, Lambda and API Gateway stay inside free tiers at this volume. CloudFront is set to the cheapest price class (North America and Europe edges).
