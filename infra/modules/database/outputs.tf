output "table_name" {
  description = "Name of the expenses table."
  value       = aws_dynamodb_table.expenses.name
}

output "table_arn" {
  description = "ARN of the expenses table."
  value       = aws_dynamodb_table.expenses.arn
}

output "gsi1_name" {
  description = "Name of the merchant index."
  value       = local.gsi1_name
}

output "gsi1_arn" {
  description = "ARN of the merchant index (for least-privilege IAM)."
  value       = "${aws_dynamodb_table.expenses.arn}/index/${local.gsi1_name}"
}
