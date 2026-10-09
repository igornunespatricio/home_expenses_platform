data "aws_region" "current" {}

resource "aws_cognito_user_pool" "this" {
  name = var.name

  # Log in with the e-mail address
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  deletion_protection = var.deletion_protection ? "ACTIVE" : "INACTIVE"

  # Personal app: users are created by you (aws cognito-idp admin-create-user), no self sign-up
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = false
    temporary_password_validity_days = 7
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  schema {
    name                = "email"
    attribute_data_type = "String"
    required            = true
    mutable             = true

    string_attribute_constraints {
      min_length = 5
      max_length = 254
    }
  }
}

resource "aws_cognito_user_pool_client" "app" {
  name         = "${var.name}-app"
  user_pool_id = aws_cognito_user_pool.this.id

  # Browser app: public client, no secret
  generate_secret = false

  # SRP login (used by Amplify) + token refresh. No plain password flow.
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  # Do not reveal whether an e-mail exists
  prevent_user_existence_errors = "ENABLED"

  access_token_validity  = 60 # minutes
  id_token_validity      = 60 # minutes
  refresh_token_validity = 30 # days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  enable_token_revocation = true
}
