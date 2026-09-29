# ---------------------------------------------------------------------------
# Lambda Layer com a dependência `requests`.
#
# A pasta .build/layer/python é gerada por build_layer.ps1 (Windows) ou
# build_layer.sh (Linux/macOS) ANTES do `terraform apply`. O script baixa
# os pacotes compilados para Linux, que é onde a Lambda roda.
# ---------------------------------------------------------------------------
data "archive_file" "requests_layer" {
  type        = "zip"
  source_dir  = "${path.module}/.build/layer"
  output_path = "${path.module}/.build/requests-layer.zip"
}

resource "aws_lambda_layer_version" "requests" {
  layer_name          = "requests${var.project_suffix}"
  filename            = data.archive_file.requests_layer.output_path
  source_code_hash    = data.archive_file.requests_layer.output_base64sha256
  compatible_runtimes = ["python3.13"]
}

# ---------------------------------------------------------------------------
# Lambda extract-bcb (código em ../lambda)
# ---------------------------------------------------------------------------
data "archive_file" "extract_bcb" {
  type        = "zip"
  source_dir  = "${path.module}/../lambda"
  output_path = "${path.module}/.build/extract-bcb.zip"
  excludes    = ["__pycache__"]
}

# Criado antes da Lambda para que o Terraform controle a retenção dos logs
# (senão a própria Lambda cria o log group, com retenção infinita).
resource "aws_cloudwatch_log_group" "extract_bcb" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "extract_bcb" {
  function_name    = local.lambda_name
  role             = aws_iam_role.extract_bcb.arn
  runtime          = "python3.13"
  handler          = "extract_bcb.lambda_handler"
  filename         = data.archive_file.extract_bcb.output_path
  source_code_hash = data.archive_file.extract_bcb.output_base64sha256
  layers           = [aws_lambda_layer_version.requests.arn]
  timeout          = 120 # 3 séries x até 30s de timeout HTTP cada, com folga
  memory_size      = 128

  environment {
    variables = {
      BUCKET_NAME   = aws_s3_bucket.data.bucket
      SERIES_CONFIG = jsonencode(var.series)
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.extract_bcb,
    aws_iam_role_policy.extract_bcb_logs,
  ]
}

# Sem retentativa automática da própria Lambda: uma falha vira alerta na hora,
# e a execução do dia seguinte já cobre o período perdido (a janela de busca
# é móvel, de 30/90 dias). Sem isso, uma falha rodaria o pipeline 3 vezes.
resource "aws_lambda_function_event_invoke_config" "extract_bcb" {
  function_name          = aws_lambda_function.extract_bcb.function_name
  maximum_retry_attempts = 0
}
