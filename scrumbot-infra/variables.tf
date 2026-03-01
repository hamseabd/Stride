variable "anthropic_api_key" {
  description = "Anthropic API key for Claude access"
  type        = string
  sensitive   = true
}

variable "twilio_auth_token" {
  description = "Twilio Auth Token for SMS webhook validation"
  type        = string
  sensitive   = true
}

variable "twilio_account_sid" {
  description = "Twilio Account SID"
  type        = string
}

variable "twilio_phone_number" {
  description = "Twilio toll-free phone number for outbound SMS (E.164 format, e.g. +18005551234)"
  type        = string
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "dynamodb_table_name" {
  description = "DynamoDB table name"
  type        = string
  default     = "stride-prod"
}

variable "image_tag" {
  description = "Docker image tag to deploy. Use git SHA in CI, 'latest' locally."
  type        = string
  default     = "latest"
}
