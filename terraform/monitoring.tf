# ---------------------------------------------------------------------------
# Alertas por e-mail: o pipeline roda sozinho, então precisa avisar quando
# algo dá errado -- tanto quando falha quanto quando simplesmente não roda.
# ---------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name = "financial-data-alerts${var.project_suffix}"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Falha: qualquer erro na Lambda (API fora do ar, dado reprovado na
# validação de qualidade, erro de permissão etc.).
resource "aws_cloudwatch_metric_alarm" "extract_errors" {
  alarm_name        = "${local.lambda_name}-errors"
  alarm_description = "A extração do Banco Central falhou. Veja os logs em /aws/lambda/${local.lambda_name}."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions = {
    FunctionName = aws_lambda_function.extract_bcb.function_name
  }

  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Falha silenciosa: a Lambda não foi executada nenhuma vez em ~26h
# (agendamento desligado, permissão do Scheduler quebrada etc.).
# Janela de 26 blocos de 1h, e não de 24h exatas: a execução diária cai
# sempre no mesmo horário, e com 24h cravadas o alarme dispararia por
# alguns minutos todo dia, entre a execução de ontem sair da janela e a
# métrica da execução de hoje chegar.
resource "aws_cloudwatch_metric_alarm" "extract_not_running" {
  alarm_name        = "${local.lambda_name}-not-running"
  alarm_description = "A extração do Banco Central não rodou nas últimas 26h. Verifique o EventBridge Scheduler."

  namespace   = "AWS/Lambda"
  metric_name = "Invocations"
  dimensions = {
    FunctionName = aws_lambda_function.extract_bcb.function_name
  }

  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 26
  datapoints_to_alarm = 26
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
