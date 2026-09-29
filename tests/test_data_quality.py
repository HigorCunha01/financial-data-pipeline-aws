import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambda"))

from data_quality import validar_registros  # noqa: E402


class TestValidarRegistros(unittest.TestCase):
    def test_registros_validos_nao_tem_problemas(self):
        registros = [
            {"data": "01/09/2026", "valor": "0.055131"},
            {"data": "02/09/2026", "valor": "5.4321"},
        ]
        self.assertEqual(validar_registros(registros), [])

    def test_lista_vazia_falha_quando_minimo_e_um(self):
        problemas = validar_registros([], min_registros=1)
        self.assertEqual(len(problemas), 1)
        self.assertIn("esperado >= 1", problemas[0])

    def test_resposta_que_nao_e_lista_falha(self):
        problemas = validar_registros({"erro": "Value(s) not found"})
        self.assertIn("esperado uma lista", problemas[0])

    def test_campo_ausente(self):
        problemas = validar_registros([{"data": "01/09/2026"}])
        self.assertIn("campo(s) ausente(s) ['valor']", problemas[0])

    def test_data_em_formato_errado(self):
        problemas = validar_registros([{"data": "2026-09-01", "valor": "1.0"}])
        self.assertIn("data inválida", problemas[0])

    def test_data_duplicada(self):
        registros = [
            {"data": "01/09/2026", "valor": "1.0"},
            {"data": "01/09/2026", "valor": "2.0"},
        ]
        problemas = validar_registros(registros)
        self.assertEqual(len(problemas), 1)
        self.assertIn("data duplicada", problemas[0])

    def test_valores_nao_numericos(self):
        for valor_ruim in ["", "abc", None, "nan", "inf", True]:
            with self.subTest(valor=valor_ruim):
                problemas = validar_registros([{"data": "01/09/2026", "valor": valor_ruim}])
                self.assertEqual(len(problemas), 1)
                self.assertIn("valor não numérico", problemas[0])

    def test_registro_que_nao_e_objeto(self):
        problemas = validar_registros(["texto solto"])
        self.assertIn("não é um objeto JSON", problemas[0])

    def test_lista_de_problemas_e_truncada(self):
        registros = [{"data": "x", "valor": "y"} for _ in range(20)]
        problemas = validar_registros(registros)
        self.assertEqual(len(problemas), 11)
        self.assertIn("e mais", problemas[-1])


if __name__ == "__main__":
    unittest.main()
