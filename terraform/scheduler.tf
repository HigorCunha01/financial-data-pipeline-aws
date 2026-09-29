# Executa a extração automaticamente, todo dia, sem ninguém precisar clicar em nada.
resource "aws_scheduler_schedule" "extract_daily" {
  name        = "financial-data-extract-daily${var.project_suffix}"
  description = "Dispara a Lambda de extração das séries do Banco Central."

  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.extract_bcb.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_retry_attempts       = 2
      maximum_event_age_in_seconds = 3600
    }
  }
}
