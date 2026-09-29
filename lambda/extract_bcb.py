"""Extrai séries temporais do Banco Central (SGS) e grava no S3.

Cada série é validada (ver data_quality.py) e gravada em JSON Lines, num
caminho particionado por série e data de execução:

    s3://<bucket>/raw/serie=<nome>/data_execucao=<AAAA-MM-DD>/dados.json

Se alguma série falhar (API fora do ar, resposta inesperada ou dado
inválido), as demais continuam sendo processadas e, no final, a execução
termina com erro -- o que dispara o alarme do CloudWatch.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from data_quality import validar_registros

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configuração padrão; em produção vem da variável de ambiente SERIES_CONFIG,
# definida pelo Terraform (variável `series`). "dias" é a janela de busca:
# o IPCA é mensal, então precisa de uma janela maior que as séries diárias
# para sempre trazer pelo menos um ponto.
SERIES_PADRAO = {
    "selic": {"codigo": 11, "dias": 30},
    "ipca": {"codigo": 433, "dias": 90},
    "dolar": {"codigo": 1, "dias": 30},
}

TIMEOUT_SEGUNDOS = 20

# A API do SGS às vezes responde 502/503 ou demora demais por alguns
# segundos. Esses erros passageiros são tentados de novo, com espera
# crescente (2s, depois 4s), antes de a série ser dada como falha.
TENTATIVAS = 3
ESPERA_BASE_SEGUNDOS = 2
STATUS_TRANSITORIOS = {429, 500, 502, 503, 504}

FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")

_s3_client = None


def get_s3_client():
    # Import e criação preguiçosos: o boto3 já vem no runtime da Lambda, e
    # assim os testes unitários rodam sem precisar dele instalado.
    global _s3_client
    if _s3_client is None:
        import boto3

        _s3_client = boto3.client("s3")
    return _s3_client


def carregar_series():
    bruto = os.environ.get("SERIES_CONFIG")
    return json.loads(bruto) if bruto else SERIES_PADRAO


def build_url(codigo_serie, data_inicial, data_final):
    return (
        f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados"
        f"?formato=json&dataInicial={data_inicial}&dataFinal={data_final}"
    )


def get_date_range(dias, hoje):
    inicio = hoje - timedelta(days=dias)
    return inicio.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y")


def requisitar_com_retentativa(url):
    for tentativa in range(1, TENTATIVAS + 1):
        ultima = tentativa == TENTATIVAS
        try:
            resposta = requests.get(url, timeout=TIMEOUT_SEGUNDOS)
        except (requests.ConnectionError, requests.Timeout) as erro:
            if ultima:
                raise
            motivo = type(erro).__name__
        else:
            if resposta.status_code not in STATUS_TRANSITORIOS or ultima:
                return resposta
            motivo = f"HTTP {resposta.status_code}"

        espera = ESPERA_BASE_SEGUNDOS * 2 ** (tentativa - 1)
        logger.warning(
            "tentativa %d/%d falhou (%s); nova tentativa em %ds: %s",
            tentativa,
            TENTATIVAS,
            motivo,
            espera,
            url,
        )
        time.sleep(espera)


def buscar_serie(codigo_serie, data_inicial, data_final):
    resposta = requisitar_com_retentativa(build_url(codigo_serie, data_inicial, data_final))

    # O SGS responde 404 quando não existe nenhum ponto no intervalo pedido.
    if resposta.status_code == 404:
        return []

    resposta.raise_for_status()
    dados = resposta.json()

    if not isinstance(dados, list):
        raise ValueError(f"resposta inesperada da API (esperado lista): {str(dados)[:200]}")

    return dados


def montar_key(nome_serie, data_execucao):
    return f"raw/serie={nome_serie}/data_execucao={data_execucao}/dados.json"


def lambda_handler(event, context):
    bucket = os.environ["BUCKET_NAME"]
    series = carregar_series()

    hoje = datetime.now(FUSO_HORARIO)
    data_execucao = hoje.strftime("%Y-%m-%d")

    gravadas = {}
    falhas = {}

    for nome_serie, config in series.items():
        try:
            data_inicial, data_final = get_date_range(config["dias"], hoje)
            dados = buscar_serie(config["codigo"], data_inicial, data_final)

            problemas = validar_registros(dados, min_registros=1)
            if problemas:
                raise ValueError("qualidade de dado: " + "; ".join(problemas))

            corpo = "\n".join(json.dumps(item, ensure_ascii=False) for item in dados)
            get_s3_client().put_object(
                Bucket=bucket,
                Key=montar_key(nome_serie, data_execucao),
                Body=corpo.encode("utf-8"),
                ContentType="application/x-ndjson",
            )

            gravadas[nome_serie] = len(dados)
            logger.info("serie=%s registros=%d gravada com sucesso", nome_serie, len(dados))

        except Exception as erro:  # noqa: BLE001 -- isola a falha de uma série das demais
            falhas[nome_serie] = str(erro)
            logger.error("serie=%s falhou: %s", nome_serie, erro)

    if falhas:
        raise RuntimeError(
            f"{len(falhas)} série(s) com falha: {json.dumps(falhas, ensure_ascii=False)}"
        )

    return {"data_execucao": data_execucao, "registros_por_serie": gravadas}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(lambda_handler(None, None))
