data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "stride_lambda_exec" {
  name               = "stride-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project = "stride"
  }
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.stride_lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "dynamodb" {
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:BatchWriteItem",
    ]
    resources = [
      aws_dynamodb_table.stride.arn,
      "${aws_dynamodb_table.stride.arn}/index/*",
    ]
  }
}

resource "aws_iam_role_policy" "dynamodb" {
  name   = "stride-dynamodb"
  role   = aws_iam_role.stride_lambda_exec.id
  policy = data.aws_iam_policy_document.dynamodb.json
}

data "aws_iam_policy_document" "xray" {
  statement {
    effect = "Allow"
    actions = [
      "xray:PutTraceSegments",
      "xray:PutTelemetryRecords",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "xray" {
  name   = "stride-xray"
  role   = aws_iam_role.stride_lambda_exec.id
  policy = data.aws_iam_policy_document.xray.json
}
