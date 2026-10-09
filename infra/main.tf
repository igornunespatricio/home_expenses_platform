terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}

locals {
  env  = terraform.workspace
  name = "${var.project_name}-${local.env}" # prefix for resource names, e.g. expense-tracker-dev
}

# Guard: only the dev and prod workspaces are valid (blocks the "default" workspace).
resource "terraform_data" "workspace_guard" {
  lifecycle {
    precondition {
      condition     = contains(["dev", "prod"], terraform.workspace)
      error_message = "Unsupported workspace '${terraform.workspace}'. Use 'dev' or 'prod' (see scripts/tf-init.sh)."
    }
  }
}

module "database" {
  source = "./modules/database"

  table_name             = "expenses-${local.env}"
  point_in_time_recovery = var.point_in_time_recovery
  deletion_protection    = var.deletion_protection
}

module "auth" {
  source = "./modules/auth"

  name                = local.name
  deletion_protection = var.deletion_protection
}

module "api" {
  source = "./modules/api"

  name       = local.name
  source_dir = "${path.root}/../api"

  table_name = module.database.table_name
  table_arn  = module.database.table_arn
  gsi_name   = module.database.gsi1_name
  gsi_arn    = module.database.gsi1_arn

  issuer_url = module.auth.issuer_url
  client_id  = module.auth.user_pool_client_id

  log_retention_days = local.env == "prod" ? 30 : 7
}

# Next module (added when built):
#   module "frontend" -> private S3 + CloudFront
