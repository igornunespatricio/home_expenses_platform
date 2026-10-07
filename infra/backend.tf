terraform {
  required_version = ">= 1.10"

  backend "s3" {
    key          = "expense-tracker/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}