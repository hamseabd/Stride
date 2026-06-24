output "api_gateway_url" {
  description = "Base URL for the Stride HTTP API"
  value       = module.api_gateway.api_endpoint
}

output "sms_function_name" {
  description = "Name of the stride-sms Lambda function"
  value       = module.lambda_sms.lambda_function_name
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB table"
  value       = aws_dynamodb_table.stride.name
}

output "ecr_push_policy_arn" {
  description = "ARN of the ECR push policy — attach to your GitHub Actions OIDC role"
  value       = aws_iam_policy.ecr_push.arn
}

output "ecr_sms_url" {
  description = "ECR repository URL for stride-sms"
  value       = aws_ecr_repository.stride["stride-sms"].repository_url
}

output "scheduler_function_name" {
  description = "Name of the stride-scheduler Lambda function"
  value       = module.lambda_scheduler.lambda_function_name
}

output "ecr_scheduler_url" {
  description = "ECR repository URL for stride-scheduler"
  value       = aws_ecr_repository.stride["stride-scheduler"].repository_url
}

output "site_url" {
  description = "S3 website URL for the Stride site"
  value       = "http://${aws_s3_bucket_website_configuration.site.website_endpoint}"
}

output "github_actions_role_arn" {
  description = "ARN of the WRITE OIDC role (apply, main only) — set as the AWS_ROLE_ARN repo secret"
  value       = aws_iam_role.github_actions.arn
}

output "github_actions_plan_role_arn" {
  description = "ARN of the READ OIDC role (plan, PRs only) — set as the AWS_PLAN_ROLE_ARN repo secret"
  value       = aws_iam_role.github_actions_plan.arn
}
