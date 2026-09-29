# ---------------------------------------------------------------------------
# Lambda extract-bcb: só pode gravar objetos dentro de raw/ do bucket.
# ---------------------------------------------------------------------------
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

resource "aws_iam_role" "extract_bcb" {
  name               = "${local.lambda_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

# Logs: só no log group desta Lambda (criado pelo Terraform em lambda.tf).
# Mais restrito que a policy gerenciada AWSLambdaBasicExecutionRole, que
# libera escrita em qualquer log group da conta.
data "aws_iam_policy_document" "extract_bcb_logs" {
  statement {
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.extract_bcb.arn}:*"]
  }
}

resource "aws_iam_role_policy" "extract_bcb_logs" {
  name   = "cloudwatch-logs-extract-bcb"
  role   = aws_iam_role.extract_bcb.id
  policy = data.aws_iam_policy_document.extract_bcb_logs.json
}

data "aws_iam_policy_document" "extract_bcb_s3" {
  statement {
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.data.arn}/raw/*"]
  }
}

resource "aws_iam_role_policy" "extract_bcb_s3" {
  name   = "s3-putobject-raw"
  role   = aws_iam_role.extract_bcb.id
  policy = data.aws_iam_policy_document.extract_bcb_s3.json
}

# ---------------------------------------------------------------------------
# EventBridge Scheduler: só pode invocar esta Lambda, e só a partir desta conta.
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "financial-data-scheduler${var.project_suffix}-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
}

data "aws_iam_policy_document" "scheduler_invoke_lambda" {
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.extract_bcb.arn,
      "${aws_lambda_function.extract_bcb.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke_lambda" {
  name   = "lambda-invoke-extract-bcb"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke_lambda.json
}
