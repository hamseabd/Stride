output "api_gateway_url" {
  description = "Base URL for the Stride HTTP API"
  value       = module.api_gateway.api_endpoint
}

output "checkin_function_name" {
  description = "Name of the stride-checkin Lambda function"
  value       = module.lambda_checkin.lambda_function_name
}

output "agent_function_name" {
  description = "Name of the stride-agent Lambda function"
  value       = module.lambda_agent.lambda_function_name
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

output "ecr_checkin_url" {
  description = "ECR repository URL for stride-checkin"
  value       = aws_ecr_repository.stride["stride-checkin"].repository_url
}

output "ecr_agent_url" {
  description = "ECR repository URL for stride-agent"
  value       = aws_ecr_repository.stride["stride-agent"].repository_url
}

output "ecr_sms_url" {
  description = "ECR repository URL for stride-sms"
  value       = aws_ecr_repository.stride["stride-sms"].repository_url
}
