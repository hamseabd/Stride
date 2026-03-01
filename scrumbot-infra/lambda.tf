locals {
  app_dir    = "${path.module}/../scrumbot-app"
  shared_dir = "${local.app_dir}/shared"

  common_env = {
    DYNAMODB_TABLE_NAME = var.dynamodb_table_name
    ENVIRONMENT         = var.environment
  }
}

# ---------------------------------------------------------------------------
# stride-checkin
# ---------------------------------------------------------------------------

module "lambda_checkin" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.0"

  function_name = "stride-checkin"
  handler       = "handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]

  source_path = [
    "${local.app_dir}/functions/checkin",
    {
      path             = local.shared_dir
      prefix_in_zip    = "shared"
      pip_requirements = false
    },
  ]

  create_role = false
  lambda_role = aws_iam_role.stride_lambda_exec.arn

  tracing_mode = "Active"
  memory_size  = 256
  timeout      = 10

  environment_variables = merge(local.common_env, {
    POWERTOOLS_SERVICE_NAME = "stride-checkin"
  })

  tags = {
    Project = "stride"
  }
}

# ---------------------------------------------------------------------------
# stride-agent
# ---------------------------------------------------------------------------

module "lambda_agent" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.0"

  function_name = "stride-agent"
  handler       = "handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]

  source_path = [
    "${local.app_dir}/functions/agent",
    {
      path             = local.shared_dir
      prefix_in_zip    = "shared"
      pip_requirements = false
    },
  ]

  create_role = false
  lambda_role = aws_iam_role.stride_lambda_exec.arn

  tracing_mode = "Active"
  memory_size  = 512
  timeout      = 30

  environment_variables = merge(local.common_env, {
    POWERTOOLS_SERVICE_NAME = "stride-agent"
    ANTHROPIC_API_KEY       = var.anthropic_api_key
  })

  tags = {
    Project = "stride"
  }
}

# ---------------------------------------------------------------------------
# stride-sms
# ---------------------------------------------------------------------------

module "lambda_sms" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "~> 7.0"

  function_name = "stride-sms"
  handler       = "handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]

  source_path = [
    "${local.app_dir}/functions/sms",
    {
      path             = local.shared_dir
      prefix_in_zip    = "shared"
      pip_requirements = false
    },
  ]

  create_role = false
  lambda_role = aws_iam_role.stride_lambda_exec.arn

  tracing_mode = "Active"
  memory_size  = 256
  timeout      = 10

  environment_variables = merge(local.common_env, {
    POWERTOOLS_SERVICE_NAME = "stride-sms"
    TWILIO_AUTH_TOKEN       = var.twilio_auth_token
    TWILIO_ACCOUNT_SID      = var.twilio_account_sid
    TWILIO_PHONE_NUMBER     = var.twilio_phone_number
  })

  tags = {
    Project = "stride"
  }
}
