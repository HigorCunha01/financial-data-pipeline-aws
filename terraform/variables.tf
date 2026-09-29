variable "aws_region" {
  description = "Região AWS onde os recursos serão criados."
  type        = string
  default     = "us-east-1"
}

variable "project_suffix" {
  description = "Sufixo aplicado aos nomes de recurso, para rodar em paralelo à versão manual sem conflitar nomes."
  type        = string
  default     = "-tf"
}

variable "alert_email" {
  description = "E-mail que recebe os alertas de falha do pipeline. Passe via terraform.tfvars (não commitado)."
  type        = string
}

variable "series" {
  description = "Séries do SGS/Banco Central a extrair. codigo = código da série no SGS; dias = janela de busca a cada execução."
  type = map(object({
    codigo = number
    dias   = number
  }))
  default = {
    selic = { codigo = 11, dias = 30 }
    ipca  = { codigo = 433, dias = 90 } # mensal: janela maior garante pelo menos 1 ponto
    dolar = { codigo = 1, dias = 30 }
  }
}

variable "schedule_expression" {
  description = "Quando a extração roda (sintaxe do EventBridge Scheduler), no fuso de schedule_timezone."
  type        = string
  default     = "cron(0 9 * * ? *)" # todo dia às 09:00
}

variable "schedule_timezone" {
  description = "Fuso horário usado pelo agendamento."
  type        = string
  default     = "America/Sao_Paulo"
}

variable "projection_start_date" {
  description = "Primeira data (AAAA-MM-DD) considerada pela partition projection do Athena."
  type        = string
  default     = "2026-01-01"
}

variable "log_retention_days" {
  description = "Por quantos dias os logs da Lambda ficam no CloudWatch (evita custo de retenção infinita)."
  type        = number
  default     = 14
}

variable "athena_bytes_scanned_cutoff" {
  description = "Limite de bytes escaneados por query no Athena. Query que passar disso é cancelada (proteção de custo)."
  type        = number
  default     = 104857600 # 100 MB
}
