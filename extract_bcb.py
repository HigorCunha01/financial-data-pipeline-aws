import requests
import boto3
import json
from datetime import datetime, timedelta

SERIES = {
    "selic": 11, "ipca": 433, "dolar": 1
}

s3_client = boto3.client("s3")

def build_url(codigo_serie, data_inicial, data_final):
    return f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_serie}/dados?formato=json&dataInicial={data_inicial}&dataFinal={data_final}"

def get_date_range():
    hoje = datetime.now()
    data_passada = hoje - timedelta(days=30)
    data_formatada = hoje.strftime("%Y-%m-%d")
    return data_passada.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y"), data_formatada

def lambda_handler(event, context):
    data_inicial, data_final, data_formatada = get_date_range()
    for nome_serie, codigo_serie in SERIES.items():
        url = build_url(codigo_serie, data_inicial, data_final)
        response = requests.get(url)
        dados = response.json()
        linhas = [json.dumps(item) for item in dados]
        key = f"raw/serie={nome_serie}/data_execucao={data_formatada}/dados.json"
        s3_client.put_object(Bucket = "higor-financial-data-raw", Key = key, Body =  "\n".join(linhas))
        print(nome_serie, dados)

if __name__ == "__main__":
    lambda_handler(None, None)