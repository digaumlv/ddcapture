"""Resolver de metricas: /api/v2/query/scalar, /api/v2/query/timeseries e o v1 legado.

Atencao as unidades de tempo: a API v2 usa epoch em MILISSEGUNDOS no corpo,
a v1 usa SEGUNDOS na querystring. Trocar as duas e o erro classico aqui.
"""

from __future__ import annotations

from typing import Any

from ..client import DatadogClient, ErroApi
from ..extractor import nome_metrica
from ..models import QuerySpec
from . import ValorBruto, tags_de_lista, unidade_de


def resolver(
    client: DatadogClient,
    spec: QuerySpec,
    inicio_s: int,
    fim_s: int,
) -> list[ValorBruto]:
    try:
        if spec.e_legada:
            return _query_v1(client, spec, inicio_s, fim_s)
        if spec.response_format == "scalar":
            return _query_escalar(client, spec, inicio_s, fim_s)
        return _query_timeseries(client, spec, inicio_s, fim_s)
    except ErroApi as exc:
        # Nome vazio de proposito: runner._nome_final usa o titulo do widget.
        # Jogar a query aqui poluiria a coluna Campo com o texto da busca.
        return [ValorBruto(nome="", valor=None, erro=str(exc))]


def _query_escalar(
    client: DatadogClient, spec: QuerySpec, inicio_s: int, fim_s: int
) -> list[ValorBruto]:
    corpo = {
        "data": {
            "type": "scalar_request",
            "attributes": {
                "from": inicio_s * 1000,
                "to": fim_s * 1000,
                "queries": spec.queries,
                "formulas": spec.formulas or _formulas_implicitas(spec),
            },
        }
    }
    resposta = client.post("/api/v2/query/scalar", corpo)
    return _ler_escalar(resposta, spec)


def _query_timeseries(
    client: DatadogClient, spec: QuerySpec, inicio_s: int, fim_s: int
) -> list[ValorBruto]:
    corpo = {
        "data": {
            "type": "timeseries_request",
            "attributes": {
                "from": inicio_s * 1000,
                "to": fim_s * 1000,
                "queries": _sem_aggregator(spec.queries),
                "formulas": spec.formulas or _formulas_implicitas(spec),
            },
        }
    }
    resposta = client.post("/api/v2/query/timeseries", corpo)
    return _ler_timeseries(resposta, spec)


def _query_v1(
    client: DatadogClient, spec: QuerySpec, inicio_s: int, fim_s: int
) -> list[ValorBruto]:
    """Formato legado requests[].q - a v1 aceita a string como esta."""
    resposta = client.get(
        "/api/v1/query",
        params={"from": inicio_s, "to": fim_s, "query": spec.query_legada},
    )

    valores: list[ValorBruto] = []
    for serie in resposta.get("series") or []:
        pontos = [p for p in (serie.get("pointlist") or []) if p and p[1] is not None]
        if not pontos:
            continue
        ts_ms, valor = pontos[-1]
        metrica = serie.get("metric") or nome_metrica(spec.query_legada or "")
        escopo = serie.get("scope") or ""
        tags = tags_de_lista([t for t in escopo.split(",") if t and t != "*"])
        valores.append(
            ValorBruto(
                nome=metrica,
                valor=float(valor),
                unidade=unidade_de(serie.get("unit")),
                timestamp=int(ts_ms) // 1000,
                tags=tags,
            )
        )

    if not valores:
        valores.append(
            ValorBruto(
                nome=nome_metrica(spec.query_legada or "") or "(sem dados)",
                valor=None,
                erro="a query nao retornou pontos na janela",
            )
        )
    return valores


def _ler_escalar(resposta: dict[str, Any], spec: QuerySpec) -> list[ValorBruto]:
    """Resposta escalar: colunas paralelas, umas de valor e outras de grupo.

    As colunas 'group' trazem as tags de cada linha; as colunas numericas trazem
    um valor por linha. O indice da linha liga as duas.
    """
    attrs = ((resposta.get("data") or {}).get("attributes")) or {}
    colunas = attrs.get("columns") or []
    if not colunas:
        # Resposta 200 sem nenhuma coluna: a query rodou e nao casou nada.
        return [ValorBruto(nome="", valor=0.0, sem_dados=True)]

    colunas_grupo = [c for c in colunas if c.get("type") == "group"]
    colunas_valor = [c for c in colunas if c.get("type") != "group"]

    valores: list[ValorBruto] = []
    for coluna in colunas_valor:
        nome_base = coluna.get("name") or spec.descricao_query()
        unidade = unidade_de(coluna.get("meta", {}).get("unit") or coluna.get("unit"))
        for linha, valor in enumerate(coluna.get("values") or []):
            tags = _tags_da_linha(colunas_grupo, linha)
            valores.append(
                ValorBruto(
                    nome=nome_base,
                    valor=None if valor is None else float(valor),
                    unidade=unidade,
                    tags=tags,
                )
            )

    if not valores:
        valores.append(
            ValorBruto(nome="", valor=0.0, sem_dados=True)
        )
    return valores


def _ler_timeseries(resposta: dict[str, Any], spec: QuerySpec) -> list[ValorBruto]:
    """De uma serie temporal guardamos o ultimo ponto com valor.

    O dashboard mostra a curva inteira, mas o que se captura por nome e um
    numero - e o ultimo ponto e o que corresponde ao 'agora' do painel.
    """
    attrs = ((resposta.get("data") or {}).get("attributes")) or {}
    series = attrs.get("series") or []
    times = attrs.get("times") or []
    matriz = attrs.get("values") or []

    valores: list[ValorBruto] = []
    for indice, serie in enumerate(series):
        if indice >= len(matriz):
            continue
        pontos = matriz[indice] or []
        ultimo_i = _ultimo_indice_valido(pontos)
        if ultimo_i is None:
            continue

        tags = tags_de_lista(serie.get("group_tags"))
        nome_base = _nome_da_serie(serie, spec, indice)
        ts_ms = times[ultimo_i] if ultimo_i < len(times) else None
        valores.append(
            ValorBruto(
                nome=nome_base,
                valor=float(pontos[ultimo_i]),
                unidade=unidade_de(serie.get("unit")),
                timestamp=int(ts_ms) // 1000 if ts_ms else None,
                tags=tags,
            )
        )

    if not valores:
        valores.append(
            ValorBruto(nome="", valor=0.0, sem_dados=True)
        )
    return valores


def _nome_da_serie(serie: dict[str, Any], spec: QuerySpec, indice: int) -> str:
    """Alias da formula > nome da query > nome da metrica."""
    idx_formula = serie.get("query_index")
    if idx_formula is not None and idx_formula < len(spec.formulas):
        alias = spec.formulas[idx_formula].get("alias")
        if alias:
            return str(alias)
    if idx_formula is not None and idx_formula < len(spec.queries):
        q = spec.queries[idx_formula]
        return str(q.get("name") or nome_metrica(str(q.get("query") or "")))
    if spec.queries:
        q = spec.queries[min(indice, len(spec.queries) - 1)]
        return str(q.get("name") or nome_metrica(str(q.get("query") or "")))
    return spec.descricao_query()


def _tags_da_linha(colunas_grupo: list[dict[str, Any]], linha: int) -> dict[str, str]:
    tags: dict[str, str] = {}
    for coluna in colunas_grupo:
        vals = coluna.get("values") or []
        if linha >= len(vals):
            continue
        tags.update(tags_de_lista(vals[linha]))
    return tags


def _ultimo_indice_valido(pontos: list[Any]) -> int | None:
    for i in range(len(pontos) - 1, -1, -1):
        if pontos[i] is not None:
            return i
    return None


def _formulas_implicitas(spec: QuerySpec) -> list[dict[str, Any]]:
    """Sem formulas declaradas, cada query vira uma formula com seu proprio nome."""
    return [{"formula": q["name"]} for q in spec.queries if q.get("name")]


def _sem_aggregator(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A API de timeseries rejeita `aggregator` nas queries."""
    return [{k: v for k, v in q.items() if k != "aggregator"} for q in queries]
