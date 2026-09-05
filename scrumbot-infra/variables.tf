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
  description = "Twilio 10DLC phone number for SMS (E.164 format, e.g. +14045551234)"
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

variable "notify_phone" {
  description = "Phone number (E.164) to receive new-user signup notifications. Empty = no notifications."
  type        = string
  default     = ""
}

variable "otel_exporter_otlp_endpoint" {
  description = "OTLP base URL. Braintrust: https://api.braintrust.dev/otel — Dynatrace: https://<env>.live.dynatrace.com/api/v2/otlp. Empty disables tracing entirely."
  type        = string
  default     = ""
}

variable "otel_exporter_otlp_headers" {
  description = "OTLP auth headers, comma-separated key=value pairs."
  type        = string
  default     = ""
  sensitive   = true
}

variable "otel_vendor" {
  description = "Set to \"braintrust\" to enable Braintrust attribute remapping. Empty leaves spans vendor-neutral."
  type        = string
  default     = ""
}

variable "otel_model_id" {
  description = "Model id stamped onto model-invoke spans so Braintrust can price them. Only used when otel_vendor is braintrust."
  type        = string
  default     = "claude-sonnet-4-6"
}
