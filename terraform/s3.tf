resource "aws_s3_bucket" "data" {
  bucket = local.bucket_name

  # Ambiente de portfólio: permite `terraform destroy` mesmo com dados dentro.
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket = aws_s3_bucket.data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Resultados de query do Athena são descartáveis -- apagados após 7 dias
# para não acumular custo de armazenamento.
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "expirar-resultados-athena"
    status = "Enabled"

    filter {
      prefix = "athena-results/"
    }

    expiration {
      days = 7
    }
  }
}
