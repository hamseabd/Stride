module "api_gateway" {
  source  = "terraform-aws-modules/apigateway-v2/aws"
  version = "~> 5.0"

  name          = "stride-api"
  protocol_type = "HTTP"

  create_default_stage = true

  routes = {
    "POST /checkin" = {
      integration = {
        uri                    = module.lambda_checkin.lambda_function_arn
        payload_format_version = "2.0"
        timeout_milliseconds   = 10000
      }
    }
    "POST /ceremony" = {
      integration = {
        uri                    = module.lambda_agent.lambda_function_arn
        payload_format_version = "2.0"
        timeout_milliseconds   = 30000
      }
    }
    "POST /sms" = {
      integration = {
        uri                    = module.lambda_sms.lambda_function_arn
        payload_format_version = "2.0"
        timeout_milliseconds   = 10000
      }
    }
  }

  tags = {
    Project     = "stride"
    Environment = var.environment
  }
}

# Lambda permissions for API Gateway to invoke each function
resource "aws_lambda_permission" "apigw_checkin" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_checkin.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.api_execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_agent" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_agent.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.api_execution_arn}/*/*"
}

resource "aws_lambda_permission" "apigw_sms" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_sms.lambda_function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${module.api_gateway.api_execution_arn}/*/*"
}
