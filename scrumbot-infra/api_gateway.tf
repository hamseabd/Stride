module "api_gateway" {
  source  = "terraform-aws-modules/apigateway-v2/aws"
  version = "~> 5.0"

  name          = "stride-api"
  protocol_type = "HTTP"

  create_domain_name = false
  create_certificate = false

  routes = {
    "POST /sms" = {
      integration = {
        uri                    = module.lambda_sms.lambda_function_arn
        payload_format_version = "2.0"
        timeout_milliseconds   = 15000
      }
    }
  }

  tags = {
    Project     = "stride"
    Environment = var.environment
  }
}

# Lambda permission for API Gateway to invoke stride-sms
resource "aws_lambda_permission" "apigw_sms" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_sms.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.api_execution_arn}/*/*"
}
