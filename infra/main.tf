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

# Next modules (added as they are built):
#   module "auth"     -> Cognito user pool + app client
#   module "api"      -> Lambda + API Gateway + JWT authorizer
#   module "frontend" -> private S3 + CloudFront
