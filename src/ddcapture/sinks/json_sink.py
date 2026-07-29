"""Saida JSON hierarquica: dashboard -> categoria -> widget -> valores.

Preserva a estrutura que o CSV achata. E a saida que outro sistema consome.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Config
from ..runner import Resultado
from . import prefixo_arquivo


def gravar(resultado: Resultado, config: Config) -> Path:
    caminho = config.saida_dir / f"{prefixo_arquivo(resultado)}.json"
    with caminho.open("w", encoding="utf-8") as fh:
        json.dump(montar(resultado), fh, ensure_ascii=False, indent=2)
    return caminho


def montar(resultado: Resultado) -> dict[str, Any]:
    categorias: list[dict[str, Any]] = []

    for categoria, medicoes in resultado.por_categoria().items():
        widgets: dict[str, dict[str, Any]] = {}
        for m in medicoes:
            chave = m.widget_id or m.widget_titulo
            widget = widgets.setdefault(
                chave,
                {
                    "widget_id": m.widget_id,
                    "titulo": m.widget_titulo,
                    "tipo": m.widget_tipo,
                    "grupo": m.grupo_pai,
                    "caminho_grupos": m.caminho_grupos,
                    "valores": [],
                },
            )
            widget["valores"].append(
                {
                    "nome": m.nome_valor,
                    "valor": m.valor,
                    "unidade": m.unidade,
                    "timestamp": m.timestamp,
                    "tags": m.tags,
                    "data_source": m.data_source,
                    "query": m.query,
                    "agregador": m.agregador,
                    "categoria_origem": m.categoria_origem,
                    "erro": m.erro,
                }
            )

        categorias.append(
            {
                "categoria": categoria,
                "total_valores": len(medicoes),
                "widgets": list(widgets.values()),
            }
        )

    return {
        "dashboard": {
            "id": resultado.dashboard_id,
            "titulo": resultado.dashboard_titulo,
        },
        "janela": {
            "from": _iso(resultado.inicio_s),
            "to": _iso(resultado.fim_s),
            "from_epoch_s": resultado.inicio_s,
            "to_epoch_s": resultado.fim_s,
        },
        "resumo": {
            "widgets_encontrados": len(resultado.widgets),
            "widgets_sem_query": sum(1 for w in resultado.widgets if w.sem_query),
            "queries_executadas": len(resultado.specs),
            "valores_capturados": len(resultado.capturados),
            "falhas": len(resultado.falhas),
            "categorias": len(categorias),
        },
        "inventario_widgets": [
            {
                "widget_id": w.widget_id,
                "titulo": w.titulo_efetivo,
                "tipo": w.tipo,
                "grupo": w.grupo_pai,
                "caminho_grupos": w.caminho_grupos,
                "sem_query": w.sem_query,
            }
            for w in resultado.widgets
        ],
        "categorias": categorias,
        "medicoes": [_medicao(m) for m in resultado.medicoes],
    }


def _medicao(m: Any) -> dict[str, Any]:
    d = asdict(m)
    d["caminho_grupos"] = list(m.caminho_grupos)
    return d


def _iso(epoch_s: int) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).isoformat(timespec="seconds")
