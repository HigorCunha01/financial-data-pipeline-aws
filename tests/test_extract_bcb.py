"""Testes da Lambda sem acessar a internet nem a AWS.

A API do Banco Central (requests.get) e o cliente do S3 são substituídos por
dublês, então os testes rodam em segundos em qualquer máquina e no CI.
"""

import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

import extract_bcb  # noqa: E402

SERIES_TESTE = {
    "selic": {"codigo": 11, "dias": 30},
    "ipca": {"codigo": 433, "dias": 90},
}

DADOS_VALIDOS = [
    {"data": "01/09/2026", "valor": "0.055131"},
    {"data": "02/09/2026", "valor": "0.055131"},
]


class RespostaFalsa:
    def __init__(self, status_code=200, corpo=None):
        self.status_code = status_code
        self._corpo = corpo

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise extract_bcb.requests.HTTPError(f"HTTP {self.status_code}")


class S3Falso:
    def __init__(self):
        self.objetos = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803 -- mesma assinatura do boto3
        self.objetos[(Bucket, Key)] = Body.decode("utf-8")


class TestFuncoesAuxiliares(unittest.TestCase):
    def test_build_url(self):
        url = extract_bcb.build_url(11, "01/08/2026", "31/08/2026")
        self.assertEqual(
            url,
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.11/dados"
            "?formato=json&dataInicial=01/08/2026&dataFinal=31/08/2026",
        )

    def test_get_date_range(self):
        hoje = datetime(2026, 9, 29)
        self.assertEqual(extract_bcb.get_date_range(30, hoje), ("30/08/2026", "29/09/2026"))

    def test_montar_key_particionada(self):
        self.assertEqual(
            extract_bcb.montar_key("selic", "2026-09-29"),
            "raw/serie=selic/data_execucao=2026-09-29/dados.json",
        )

    def test_series_vem_da_variavel_de_ambiente(self):
        with mock.patch.dict(os.environ, {"SERIES_CONFIG": json.dumps(SERIES_TESTE)}):
            self.assertEqual(extract_bcb.carregar_series(), SERIES_TESTE)

    def test_series_padrao_sem_variavel_de_ambiente(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(extract_bcb.carregar_series(), extract_bcb.SERIES_PADRAO)


class TestBuscarSerie(unittest.TestCase):
    def setUp(self):
        # Não esperar de verdade entre as tentativas: o teste rodaria em segundos.
        patch = mock.patch.object(extract_bcb.time, "sleep")
        self.sleep = patch.start()
        self.addCleanup(patch.stop)

    @mock.patch.object(extract_bcb.requests, "get")
    def test_404_significa_sem_dados_no_intervalo(self, get):
        get.return_value = RespostaFalsa(status_code=404)
        self.assertEqual(extract_bcb.buscar_serie(433, "01/09/2026", "29/09/2026"), [])
        self.assertEqual(get.call_count, 1)  # 404 não é passageiro: sem nova tentativa

    @mock.patch.object(extract_bcb.requests, "get")
    def test_erro_passageiro_seguido_de_sucesso(self, get):
        get.side_effect = [RespostaFalsa(status_code=502), RespostaFalsa(corpo=DADOS_VALIDOS)]

        dados = extract_bcb.buscar_serie(433, "01/07/2026", "29/09/2026")

        self.assertEqual(dados, DADOS_VALIDOS)
        self.assertEqual(get.call_count, 2)
        self.sleep.assert_called_once_with(2)

    @mock.patch.object(extract_bcb.requests, "get")
    def test_timeout_seguido_de_sucesso(self, get):
        get.side_effect = [
            extract_bcb.requests.Timeout("demorou"),
            RespostaFalsa(corpo=DADOS_VALIDOS),
        ]
        self.assertEqual(extract_bcb.buscar_serie(11, "01/09/2026", "29/09/2026"), DADOS_VALIDOS)

    @mock.patch.object(extract_bcb.requests, "get")
    def test_erro_passageiro_persistente_e_propagado(self, get):
        get.return_value = RespostaFalsa(status_code=503)

        with self.assertRaises(extract_bcb.requests.HTTPError):
            extract_bcb.buscar_serie(11, "01/09/2026", "29/09/2026")

        self.assertEqual(get.call_count, extract_bcb.TENTATIVAS)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [2, 4])

    @mock.patch.object(extract_bcb.requests, "get")
    def test_falha_de_conexao_persistente_e_propagada(self, get):
        get.side_effect = extract_bcb.requests.ConnectionError("sem rede")

        with self.assertRaises(extract_bcb.requests.ConnectionError):
            extract_bcb.buscar_serie(11, "01/09/2026", "29/09/2026")

        self.assertEqual(get.call_count, extract_bcb.TENTATIVAS)

    @mock.patch.object(extract_bcb.requests, "get")
    def test_erro_definitivo_nao_e_tentado_de_novo(self, get):
        get.return_value = RespostaFalsa(status_code=400)

        with self.assertRaises(extract_bcb.requests.HTTPError):
            extract_bcb.buscar_serie(11, "01/09/2026", "29/09/2026")

        self.assertEqual(get.call_count, 1)
        self.sleep.assert_not_called()

    @mock.patch.object(extract_bcb.requests, "get")
    def test_resposta_que_nao_e_lista_falha(self, get):
        get.return_value = RespostaFalsa(corpo={"error": "algo deu errado"})
        with self.assertRaises(ValueError):
            extract_bcb.buscar_serie(11, "01/09/2026", "29/09/2026")

    @mock.patch.object(extract_bcb.requests, "get")
    def test_usa_timeout(self, get):
        get.return_value = RespostaFalsa(corpo=DADOS_VALIDOS)
        extract_bcb.buscar_serie(11, "01/09/2026", "29/09/2026")
        self.assertEqual(get.call_args.kwargs["timeout"], extract_bcb.TIMEOUT_SEGUNDOS)


class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        self.s3 = S3Falso()
        patches = [
            mock.patch.object(extract_bcb, "get_s3_client", return_value=self.s3),
            mock.patch.dict(
                os.environ,
                {"BUCKET_NAME": "bucket-teste", "SERIES_CONFIG": json.dumps(SERIES_TESTE)},
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    @mock.patch.object(extract_bcb.requests, "get")
    def test_grava_json_lines_particionado_para_cada_serie(self, get):
        get.return_value = RespostaFalsa(corpo=DADOS_VALIDOS)

        resultado = extract_bcb.lambda_handler({}, None)

        data_execucao = resultado["data_execucao"]
        self.assertEqual(resultado["registros_por_serie"], {"selic": 2, "ipca": 2})
        self.assertEqual(len(self.s3.objetos), 2)

        corpo = self.s3.objetos[
            ("bucket-teste", f"raw/serie=selic/data_execucao={data_execucao}/dados.json")
        ]
        linhas = corpo.split("\n")
        self.assertEqual([json.loads(linha) for linha in linhas], DADOS_VALIDOS)

    @mock.patch.object(extract_bcb.requests, "get")
    def test_serie_invalida_nao_e_gravada_e_execucao_falha(self, get):
        def resposta_por_serie(url, timeout):
            if "sgs.433" in url:
                return RespostaFalsa(corpo=[{"data": "01/09/2026", "valor": "abc"}])
            return RespostaFalsa(corpo=DADOS_VALIDOS)

        get.side_effect = resposta_por_serie

        with self.assertRaises(RuntimeError) as contexto:
            extract_bcb.lambda_handler({}, None)

        self.assertIn("ipca", str(contexto.exception))
        self.assertIn("qualidade de dado", str(contexto.exception))
        # A série válida continua sendo gravada; só a inválida fica de fora.
        chaves = [key for (_, key) in self.s3.objetos]
        self.assertEqual(len(chaves), 1)
        self.assertTrue(chaves[0].startswith("raw/serie=selic/"))

    @mock.patch.object(extract_bcb.requests, "get")
    def test_serie_sem_dados_falha_na_validacao(self, get):
        get.return_value = RespostaFalsa(status_code=404)

        with self.assertRaises(RuntimeError) as contexto:
            extract_bcb.lambda_handler({}, None)

        self.assertIn("esperado >= 1", str(contexto.exception))
        self.assertEqual(self.s3.objetos, {})


if __name__ == "__main__":
    unittest.main()
