# ---------------------------------------------------------------------------
# EventBridge rule — triggers stride-scheduler every 15 minutes
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "scheduler" {
  name                = "stride-scheduler-rule"
  description         = "Trigger stride-scheduler Lambda every 15 minutes"
  schedule_expression = "rate(15 minutes)"

  tags = {
    Project = "stride"
  }
}

resource "aws_cloudwatch_event_target" "scheduler" {
  rule = aws_cloudwatch_event_rule.scheduler.name
  arn  = module.lambda_scheduler.lambda_function_arn
}

resource "aws_lambda_permission" "eventbridge_scheduler" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = module.lambda_scheduler.lambda_function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scheduler.arn
}
