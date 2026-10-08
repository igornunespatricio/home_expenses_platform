resource "aws_dynamodb_table" "expenses" {
  name         = var.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk" # USER#<cognito-sub>
  range_key    = "sk" # EXP#<date>#<ulid>

  deletion_protection_enabled = var.deletion_protection

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  # Index keys: "all spending at one merchant"
  attribute {
    name = "gsi1pk" # USER#<sub>#MERCHANT#<merchant>
    type = "S"
  }

  attribute {
    name = "gsi1sk" # <date>#<ulid>
    type = "S"
  }

  global_secondary_index {
    name            = local.gsi1_name
    projection_type = "ALL"

    key_schema {
      attribute_name = "gsi1pk"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "gsi1sk"
      key_type       = "RANGE"
    }
  }

  point_in_time_recovery {
    enabled = var.point_in_time_recovery
  }
}

locals {
  gsi1_name = "gsi1"
}
