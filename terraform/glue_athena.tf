# ---------------------------------------------------------------------------
# Catálogo: database + tabela declarados como código.
#
# Na versão manual, um Glue Crawler inferia o schema e registrava as
# partições. Aqui o schema é declarado explicitamente e as partições são
# resolvidas pelo próprio Athena via "partition projection" -- toda partição
# nova (série/dia) fica consultável na hora, sem rodar crawler nenhum.
# ---------------------------------------------------------------------------
resource "aws_glue_catalog_database" "financial_data" {
  name        = "financial_data${replace(var.project_suffix, "-", "_")}"
  description = "Indicadores econômicos do Banco Central (Selic, IPCA, dólar)."
}

resource "aws_glue_catalog_table" "raw" {
  name          = "raw"
  database_name = aws_glue_catalog_database.financial_data.name
  table_type    = "EXTERNAL_TABLE"
  description   = "Dado bruto da API SGS, em JSON Lines, particionado por série e data de execução."

  parameters = {
    "classification" = "json"
    "EXTERNAL"       = "TRUE"

    "projection.enabled" = "true"

    "projection.serie.type"   = "enum"
    "projection.serie.values" = join(",", keys(var.series))

    "projection.data_execucao.type"          = "date"
    "projection.data_execucao.format"        = "yyyy-MM-dd"
    "projection.data_execucao.range"         = "${var.projection_start_date},NOW"
    "projection.data_execucao.interval"      = "1"
    "projection.data_execucao.interval.unit" = "DAYS"

    "storage.location.template" = "s3://${aws_s3_bucket.data.bucket}/raw/serie=$${serie}/data_execucao=$${data_execucao}/"
  }

  partition_keys {
    name = "serie"
    type = "string"
  }

  partition_keys {
    name = "data_execucao"
    type = "string"
  }

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.data.bucket}/raw/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }

    columns {
      name    = "data"
      type    = "string"
      comment = "Data de referência no formato dd/mm/aaaa (como vem da API)."
    }

    columns {
      name    = "valor"
      type    = "string"
      comment = "Valor do indicador como texto (use CAST(valor AS double))."
    }
  }
}

# ---------------------------------------------------------------------------
# Athena: workgroup com local de resultado fixo e limite de custo por query.
# ---------------------------------------------------------------------------
resource "aws_athena_workgroup" "financial_data" {
  name          = "financial-data${var.project_suffix}"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff
    publish_cloudwatch_metrics_enabled = true

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

resource "aws_athena_named_query" "ultimos_valores" {
  name        = "ultimos-valores-por-serie"
  description = "Valores da execução mais recente de cada série, com data e valor já tipados."
  workgroup   = aws_athena_workgroup.financial_data.id
  database    = aws_glue_catalog_database.financial_data.name

  # Filtrar data_execucao limita as partições lidas (Athena cobra por dado escaneado).
  query = <<-SQL
    WITH ultima_execucao AS (
      SELECT serie, max(data_execucao) AS data_execucao
      FROM raw
      WHERE data_execucao >= date_format(current_date - interval '7' day, '%Y-%m-%d')
      GROUP BY serie
    )
    SELECT
      r.serie,
      date(date_parse(r.data, '%d/%m/%Y')) AS data,
      CAST(r.valor AS double)             AS valor
    FROM raw r
    JOIN ultima_execucao u
      ON r.serie = u.serie
     AND r.data_execucao = u.data_execucao
    ORDER BY r.serie, data DESC
  SQL
}
