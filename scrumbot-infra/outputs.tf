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
