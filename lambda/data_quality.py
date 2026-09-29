"""Validações de qualidade de dado aplicadas antes de gravar no S3.

Checagens leves, sem dependência externa, rodando dentro da própria Lambda:
se uma série vier quebrada da API, ela NÃO é gravada e a execução falha
(o que dispara o alarme do CloudWatch -> e-mail via SNS).
"""

import math
from datetime import datetime

CAMPOS_OBRIGATORIOS = {"data", "valor"}
FORMATO_DATA = "%d/%m/%Y"
MAX_PROBLEMAS_REPORTADOS = 10


def validar_registros(registros, min_registros=1):
    """Retorna a lista de problemas encontrados (lista vazia = dado válido)."""
    if not isinstance(registros, list):
        return [f"esperado uma lista de registros, recebido {type(registros).__name__}"]

    if len(registros) < min_registros:
        return [f"esperado >= {min_registros} registro(s), recebido {len(registros)}"]

    problemas = []
    datas_vistas = set()

    for i, registro in enumerate(registros):
        if not isinstance(registro, dict):
            problemas.append(f"registro {i}: não é um objeto JSON")
            continue

        faltando = CAMPOS_OBRIGATORIOS - registro.keys()
        if faltando:
            problemas.append(f"registro {i}: campo(s) ausente(s) {sorted(faltando)}")
            continue

        data = registro["data"]
        valor = registro["valor"]

        if not _data_valida(data):
            problemas.append(f"registro {i}: data inválida {data!r}")
        elif data in datas_vistas:
            problemas.append(f"registro {i}: data duplicada {data!r}")
        else:
            datas_vistas.add(data)

        if not _valor_valido(valor):
            problemas.append(f"registro {i}: valor não numérico {valor!r}")

    if len(problemas) > MAX_PROBLEMAS_REPORTADOS:
        restantes = len(problemas) - MAX_PROBLEMAS_REPORTADOS
        problemas = problemas[:MAX_PROBLEMAS_REPORTADOS] + [f"... e mais {restantes} problema(s)"]

    return problemas


def _data_valida(data):
    if not isinstance(data, str):
        return False
    try:
        datetime.strptime(data, FORMATO_DATA)
    except ValueError:
        return False
    return True


def _valor_valido(valor):
    if isinstance(valor, bool):
        return False
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError):
        return False
