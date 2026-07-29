"""Resolver de logs e demais fontes de eventos.

Widgets com data_source logs/rum/spans/events tambem sao aceitos pela
/api/v2/query/scalar. Quando ela recusa, cai para /api/v2/logs/analytics/aggregate,
que atende o caso de logs puro.
"""

from __future__ import annotations

from typing import Any

from ..client import DatadogClient, ErroApi
from ..models import QuerySpec
from . import ValorBruto, tags_de_lista


def resolver(
    client: DatadogClient,
    spec: QuerySpec,
    inicio_s: int,
    fim_s: int,
) -> list[ValorBruto]:
    # Preferimos a query unificada: ela entende o mesmo shape do widget.
    try:
        from .metrics import resolver as resolver_metricas

        return resolver_metricas(client, spec, inicio_s, fim_s)
    except ErroApi:
        pass

    if spec.data_source != "logs":
        return [
            ValorBruto(
                nome="",
                valor=None,
                erro=f"data_source {spec.data_source} nao pode ser consultado diretamente",
            )
        ]

    try:
        return _aggregate_logs(client, spec, inicio_s, fim_s)
    except ErroApi as exc:
        return [ValorBruto(nome="", valor=None, erro=str(exc))]


def _aggregate_logs(
    client: DatadogClient, spec: QuerySpec, inicio_s: int, fim_s: int
) -> list[ValorBruto]:
    q = spec.queries[0] if spec.queries else {}
    busca = (q.get("search") or {}).get("query", "*")
    compute = q.get("compute") or {"aggregation": "count"}
    group_by = q.get("group_by") or []

    corpo: dict[str, Any] = {
        "compute": [_compute_v2(compute)],
        "filter": {
            "query": busca,
            "from": str(inicio_s * 1000),
            "to": str(fim_s * 1000),
        },
    }
    if group_by:
        corpo["group_by"] = [_group_by_v2(g) for g in group_by]

    resposta = client.post("/api/v2/logs/analytics/aggregate", corpo)
    return _ler_buckets(resposta, q)


def _compute_v2(compute: dict[str, Any]) -> dict[str, Any]:
    saida: dict[str, Any] = {
        "aggregation": compute.get("aggregation") or "count",
        "type": "total",
    }
    if compute.get("metric"):
        saida["metric"] = compute["metric"]
    return saida


def _group_by_v2(g: Any) -> dict[str, Any]:
    if isinstance(g, str):
        return {"facet": g, "limit": 10}
    return {
        "facet": g.get("facet") or g.get("name") or "",
        "limit": g.get("limit") or 10,
    }


def _ler_buckets(resposta: dict[str, Any], q: dict[str, Any]) -> list[ValorBruto]:
    buckets = ((resposta.get("data") or {}).get("buckets")) or resposta.get("buckets") or []
    nome_base = str(q.get("name") or "logs")

    valores: list[ValorBruto] = []
    for bucket in buckets:
        tags = {str(k): str(v) for k, v in (bucket.get("by") or {}).items()}
        for chave, valor in (bucket.get("computes") or {}).items():
            if not isinstance(valor, (int, float)):
                continue
            # O escopo nao entra aqui: runner._nome_final o compoe a partir de tags.
            nome = f"{nome_base}.{chave}" if chave != "c0" else nome_base
            valores.append(ValorBruto(nome=nome, valor=float(valor), tags=tags))

    if not valores:
        # Busca sem buckets = nenhuma ocorrencia na janela. Zero e a resposta.
        valores.append(ValorBruto(nome="", valor=0.0, sem_dados=True))
    return valores


__all__ = ["resolver", "tags_de_lista"]
