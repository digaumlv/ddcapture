"""Saida CSV plana: uma linha por valor capturado."""

from __future__ import annotations

import csv
from pathlib import Path

from ..config import Config
from ..runner import Resultado
from . import prefixo_arquivo

# Ordem das colunas na saida. As tags de dimensao entram depois destas.
COLUNAS_BASE = [
    "categoria",
    "categoria_origem",
    "grupo_pai",
    "caminho_grupos",
    "widget_titulo",
    "widget_tipo",
    "nome_valor",
    "valor",
    "unidade",
    "timestamp",
    "data_source",
    "agregador",
    "query",
    "widget_id",
    "dashboard_id",
    "dashboard_titulo",
    "capturado_em",
    "sem_dados",
    "erro",
]


def gravar(resultado: Resultado, config: Config) -> Path:
    caminho = config.saida_dir / f"{prefixo_arquivo(resultado)}.csv"
    chaves_tag = config.tags_dimensao
    colunas = COLUNAS_BASE + chaves_tag

    # utf-8-sig: sem o BOM o Excel em pt-BR abre os acentos errados.
    with caminho.open("w", encoding="utf-8-sig", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=colunas, extrasaction="ignore", delimiter=";")
        escritor.writeheader()
        for m in resultado.medicoes:
            escritor.writerow(m.para_linha(chaves_tag))

    return caminho
