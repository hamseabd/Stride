locals {
  common_env = {
    DYNAMODB_TABLE_NAME = var.dynamodb_table_name
    ENVIRONMENT         = var.environment
  }

  otel_env = var.otel_exporter_otlp_endpoint != "" ? merge({
    OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_exporter_otlp_endpoint
    OTEL_EXPORTER_OTLP_HEADERS  = var.otel_exporter_otlp_headers
    }, var.otel_vendor != "" ? {
    OTEL_VENDOR   = var.otel_vendor
    OTEL_MODEL_ID = var.otel_model_id
  } : {}) : {}
}

# ---------------------------------------------------------------------------
# stride-sms
# ---------------------------------------------------------------------------

module "lambda_sms" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.0"

  function_name  = "stride-sms"
  create_package = false
  package_type   = "Image"
  image_uri      = "${aws_ecr_repository.stride["stride-sms"].repository_url}:${var.image_tag}"
  architectures  = ["arm64"]

  create_role = false
  lambda_role = aws_iam_role.stride_lambda_exec.arn

  tracing_mode = "Active"
  memory_size  = 256
  timeout      = 30

  environment_variables = merge(local.common_env, {
    POWERTOOLS_SERVICE_NAME = "stride-sms"
    ANTHROPIC_API_KEY       = var.anthropic_api_key
    TWILIO_AUTH_TOKEN       = var.twilio_auth_token
    TWILIO_ACCOUNT_SID      = var.twilio_account_sid
    TWILIO_PHONE_NUMBER     = var.twilio_phone_number
    NOTIFY_PHONE            = var.notify_phone
  }, local.otel_env)

  tags = {
    Project = "stride"
  }
}

# ---------------------------------------------------------------------------
# stride-scheduler
# ---------------------------------------------------------------------------

module "lambda_scheduler" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.0"

  function_name  = "stride-scheduler"
  create_package = false
  package_type   = "Image"
  image_uri      = "${aws_ecr_repository.stride["stride-scheduler"].repository_url}:${var.image_tag}"
  architectures  = ["arm64"]

  create_role = false
  lambda_role = aws_iam_role.stride_lambda_exec.arn

  tracing_mode = "Active"
  memory_size  = 256
  timeout      = 60

  environment_variables = merge(local.common_env, {
    POWERTOOLS_SERVICE_NAME = "stride-scheduler"
    TWILIO_AUTH_TOKEN       = var.twilio_auth_token
    TWILIO_ACCOUNT_SID      = var.twilio_account_sid
    TWILIO_PHONE_NUMBER     = var.twilio_phone_number
  }, local.otel_env)

  tags = {
    Project = "stride"
  }
}
