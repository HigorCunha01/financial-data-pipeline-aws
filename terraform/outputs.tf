output "bucket_name" {
  description = "Bucket com os dados brutos (raw/) e os resultados do Athena (athena-results/)."
  value       = aws_s3_bucket.data.bucket
}

output "lambda_function_name" {
  description = "Use para rodar a extração manualmente: aws lambda invoke --function-name <este valor> out.json"
  value       = aws_lambda_function.extract_bcb.function_name
}

output "glue_database" {
  value = aws_glue_catalog_database.financial_data.name
}

output "athena_workgroup" {
  description = "Selecione este workgroup no console do Athena antes de rodar queries."
  value       = aws_athena_workgroup.financial_data.name
}

output "schedule_name" {
  value = aws_scheduler_schedule.extract_daily.name
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}
