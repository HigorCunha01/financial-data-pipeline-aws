terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Tags aplicadas automaticamente em todo recurso que aceita tag -- permite
  # filtrar o custo deste projeto no Cost Explorer (FinOps).
  default_tags {
    tags = {
      Project   = "financial-data-pipeline"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Nome de bucket precisa ser único no mundo todo; o Account ID garante isso.
  bucket_name = "financial-data-raw${var.project_suffix}-${local.account_id}"

  lambda_name = "extract-bcb${var.project_suffix}"
}
