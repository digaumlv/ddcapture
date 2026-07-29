"""Fase 2a: transformar cada widget nas queries executaveis (QuerySpec).

Dois formatos convivem nos dashboards:

  moderno  requests[].queries[] + requests[].formulas[]  -> vai quase 1:1 para /api/v2/query/*
  legado   requests[].q (string unica)                   -> vai para GET /api/v1/query

Widgets antigos e widgets criados pela UI recente aparecem no mesmo dashboard,
entao os dois caminhos precisam existir.
"""

from __future__ import annotations

import re
from typing import Any

from .dashboard import substituir_template_vars
from .models import QuerySpec, Widget

# Widgets cujo numero exibido e o ultimo ponto, nao a media da janela.
_TIPOS_ULTIMO_VALOR = frozenset({"query_value", "alert_value", "check_status"})

# Widgets que sempre pedem valor escalar, mesmo sem response_format declarado.
_TIPOS_ESCALARES = frozenset(
    {"query_value", "toplist", "table", "query_table", "sunburst", "pie_chart",
     "treemap", "geomap", "alert_value", "change", "hostmap", "scatterplot"}
)

# data_sources que o resolver de metricas atende via /api/v2/query/*.
DATA_SOURCES_METRICAS = frozenset({"metrics", "cloud_cost", "metrics_v2"})
DATA_SOURCES_EVENTOS = frozenset(
    {"logs", "rum", "events", "spans", "audit", "profiles", "ci_pipelines",
     "ci_tests", "network", "security_signals", "incident_analytics", "database_queries"}
)

_AGREGADOR_VALIDO = frozenset({"avg", "sum", "min", "max", "last", "percentile", "area", "l2norm"})

# Prefixo de agregacao de uma query classica: "avg:system.cpu.user{...}".
_PREFIXO_AGG = re.compile(r"^\s*(avg|sum|min|max|last|count|pct|percentile)\s*:", re.I)


def extrair(
    widget: Widget,
    valores_vars: dict[str, str],
    agregador_padrao: str = "avg",
    prefixos: dict[str, str] | None = None,
) -> list[QuerySpec]:
    """Todas as queries executaveis de um widget."""
    if widget.sem_query:
        return []

    prefixos = prefixos or {}
    definition = widget.definition
    specs: list[QuerySpec] = []

    # Widgets de SLO nao usam requests - o id do SLO fica na propria definition.
    if widget.tipo in ("slo", "slo_list"):
        return _extrair_slo(widget)

    requests_ = definition.get("requests")
    # Alguns widgets (ex.: alert_value) usam um request unico como objeto.
    if isinstance(requests_, dict):
        requests_ = [requests_]
    if not requests_:
        return _extrair_sem_requests(widget)

    for indice, req in enumerate(requests_):
        if not isinstance(req, dict):
            continue
        spec = _extrair_request(
            widget, indice, req, valores_vars, agregador_padrao, prefixos
        )
        if spec is not None:
            specs.append(spec)

    return specs


def _extrair_request(
    widget: Widget,
    indice: int,
    req: dict[str, Any],
    valores_vars: dict[str, str],
    agregador_padrao: str,
    prefixos: dict[str, str],
) -> QuerySpec | None:
    response_format = str(
        req.get("response_format")
        or ("scalar" if widget.tipo in _TIPOS_ESCALARES else "timeseries")
    )
    agregador = _agregador_do_widget(widget, agregador_padrao)

    queries_brutas = req.get("queries")
    if queries_brutas:
        queries: list[dict[str, Any]] = []
        for q in queries_brutas:
            if not isinstance(q, dict):
                continue
            queries.append(
                _normalizar_query(q, valores_vars, agregador, response_format, prefixos)
            )
        if not queries:
            return None

        # query_table guarda compute e group_by FORA da query.
        if str(req.get("request_type") or "") == "table":
            _completar_query_de_tabela(req, queries, valores_vars, prefixos)

        data_source = str(queries[0].get("data_source") or "metrics")
        return QuerySpec(
            widget=widget,
            indice_request=indice,
            data_source=data_source,
            response_format=response_format,
            queries=queries,
            formulas=_normalizar_formulas(req.get("formulas")),
        )

    # Formato legado: uma string em `q`.
    q_legada = req.get("q")
    if isinstance(q_legada, str) and q_legada.strip():
        return QuerySpec(
            widget=widget,
            indice_request=indice,
            data_source="metrics",
            response_format=response_format,
            query_legada=substituir_template_vars(q_legada, valores_vars, prefixos),
        )

    # Widgets de log/evento antigos guardam a busca em log_query/apm_query/etc.
    for chave in ("log_query", "apm_query", "rum_query", "event_query",
                  "network_query", "process_query", "security_query"):
        sub = req.get(chave)
        if isinstance(sub, dict):
            return _extrair_query_antiga(
                widget, indice, chave, sub, valores_vars, response_format, prefixos
            )

    return None


def _normalizar_query(
    q: dict[str, Any],
    valores_vars: dict[str, str],
    agregador: str,
    response_format: str,
    prefixos: dict[str, str],
) -> dict[str, Any]:
    """Deixa a query no shape aceito pela API v2.

    O aggregator so e valido (e obrigatorio) em consultas escalares de metricas.
    """
    saida: dict[str, Any] = {
        "data_source": str(q.get("data_source") or "metrics"),
        "name": str(q.get("name") or "query_a"),
    }

    if "query" in q:
        saida["query"] = substituir_template_vars(str(q["query"]), valores_vars, prefixos)

    # Nem toda fonte usa `query`: eventos/logs trazem search/compute/group_by,
    # e um widget de dataset (celula de notebook) e identificado por
    # dataset_id + dataset_provider. Descartar qualquer um destes faz a API
    # responder 'Invalid query input'.
    for chave in ("search", "compute", "group_by", "indexes", "storage",
                  "compute_query", "event_size",
                  "dataset_id", "dataset_provider", "query_filter", "sort"):
        if chave in q:
            saida[chave] = _substituir_recursivo(q[chave], valores_vars, prefixos)

    if saida["data_source"] in DATA_SOURCES_METRICAS and response_format == "scalar":
        agg = str(q.get("aggregator") or agregador)
        saida["aggregator"] = agg if agg in _AGREGADOR_VALIDO else "avg"

    return saida


def _substituir_recursivo(
    valor: Any, valores_vars: dict[str, str], prefixos: dict[str, str] | None = None
) -> Any:
    if isinstance(valor, str):
        return substituir_template_vars(valor, valores_vars, prefixos)
    if isinstance(valor, list):
        return [_substituir_recursivo(v, valores_vars, prefixos) for v in valor]
    if isinstance(valor, dict):
        return {k: _substituir_recursivo(v, valores_vars, prefixos) for k, v in valor.items()}
    return valor


# Teto por facet numa query escalar agrupada. `rows.sort.limit` do widget e o
# limite de LINHAS DA TABELA, nao por facet: com dois group_by, repassa-lo
# direto (500) faz a API responder 'Invalid query input'. Medido: com dois
# facets, 200 falha e 100 passa; com um facet, 500 passa.
_LIMITE_MAX_POR_FACET = 100


def _limite_por_facet(rows: dict[str, Any]) -> int:
    limite = ((rows.get("sort") or {}).get("limit")) or 10
    try:
        limite = int(limite)
    except (TypeError, ValueError):
        return 10
    # So limita quando ha mais de um agrupamento - com um so, o teto do widget
    # e aceito e trunca menos.
    if len(rows.get("group_by") or []) > 1:
        return min(limite, _LIMITE_MAX_POR_FACET)
    return limite


def _completar_query_de_tabela(
    req: dict[str, Any],
    queries: list[dict[str, Any]],
    valores_vars: dict[str, str],
    prefixos: dict[str, str],
) -> None:
    """Traz compute e group_by de um query_table para dentro da query.

    Num widget de tabela a query so carrega o `search`; a agregacao fica em
    columns[].compute e o agrupamento em rows.group_by[].group_keys[]. Enviar a
    query como esta faz a API v2 responder 'Error decoding payload'.

    As formulas das colunas NAO sao aproveitadas: elas referenciam o nome da
    coluna ('default_zero(column1)'), nao o da query, que e o que a API espera.
    Sem elas, _formulas_implicitas gera a formula certa a partir do nome da query.
    """
    computes: dict[str, dict[str, Any]] = {}
    for coluna in req.get("columns") or []:
        if not isinstance(coluna, dict) or coluna.get("type") != "compute":
            continue
        compute = coluna.get("compute") or {}
        alvo = str(compute.get("query") or "")
        if not alvo or alvo in computes:
            continue
        item: dict[str, Any] = {"aggregation": compute.get("aggregation") or "count"}
        if compute.get("metric"):
            item["metric"] = compute["metric"]
        computes[alvo] = item

    rows = req.get("rows") or {}
    limite = _limite_por_facet(rows)
    grupos: dict[str, list[dict[str, Any]]] = {}
    for grupo in rows.get("group_by") or []:
        for chave in (grupo or {}).get("group_keys") or []:
            if not isinstance(chave, dict):
                continue
            alvo = str(chave.get("query") or "")
            facet = chave.get("group_key")
            if alvo and facet:
                grupos.setdefault(alvo, []).append(
                    {"facet": substituir_template_vars(str(facet), valores_vars, prefixos),
                     "limit": limite}
                )

    for q in queries:
        nome = str(q.get("name") or "")
        if "compute" not in q and nome in computes:
            q["compute"] = computes[nome]
        if "group_by" not in q and nome in grupos:
            q["group_by"] = grupos[nome]


def _normalizar_formulas(formulas: Any) -> list[dict[str, Any]]:
    """Mantem so formula e alias - os campos de estilo a API de query rejeita."""
    if not formulas:
        return []
    saida = []
    for f in formulas:
        if not isinstance(f, dict) or not f.get("formula"):
            continue
        item: dict[str, Any] = {"formula": str(f["formula"])}
        if f.get("alias"):
            item["alias"] = str(f["alias"])
        saida.append(item)
    return saida


def _agregador_do_widget(widget: Widget, agregador_padrao: str) -> str:
    """query_value mostra o ultimo ponto; os demais, a agregacao configurada."""
    if widget.tipo in _TIPOS_ULTIMO_VALOR:
        return "last"
    return agregador_padrao


def _extrair_slo(widget: Widget) -> list[QuerySpec]:
    definition = widget.definition
    slo_id = definition.get("slo_id") or definition.get("id")
    if not slo_id:
        return []
    return [
        QuerySpec(
            widget=widget,
            indice_request=0,
            data_source="slo",
            response_format="scalar",
            extra={
                "slo_id": str(slo_id),
                "time_windows": definition.get("time_windows") or ["7d"],
            },
        )
    ]


def _extrair_sem_requests(widget: Widget) -> list[QuerySpec]:
    """Widgets de monitor: o dado vem da API de monitores, nao de uma query."""
    if widget.tipo not in ("manage_status", "monitor_summary", "alert_graph"):
        return []

    definition = widget.definition
    return [
        QuerySpec(
            widget=widget,
            indice_request=0,
            data_source="monitors",
            response_format="scalar",
            extra={
                "query": definition.get("query") or definition.get("alert_id") or "",
                "alert_id": definition.get("alert_id"),
            },
        )
    ]


def _extrair_query_antiga(
    widget: Widget,
    indice: int,
    chave: str,
    sub: dict[str, Any],
    valores_vars: dict[str, str],
    response_format: str,
    prefixos: dict[str, str],
) -> QuerySpec:
    """Converte log_query/apm_query/etc para o shape v2 de eventos."""
    data_source = {
        "log_query": "logs",
        "apm_query": "spans",
        "rum_query": "rum",
        "event_query": "events",
        "network_query": "network",
        "process_query": "process",
        "security_query": "security_signals",
    }.get(chave, "logs")

    busca = ((sub.get("search") or {}).get("query")) or sub.get("query") or ""
    compute = sub.get("compute") or (sub.get("multi_compute") or [{}])[0]

    query: dict[str, Any] = {
        "data_source": data_source,
        "name": "query_a",
        "search": {"query": substituir_template_vars(str(busca), valores_vars)},
        "compute": _substituir_recursivo(compute, valores_vars) or {"aggregation": "count"},
    }
    if sub.get("group_by"):
        query["group_by"] = _substituir_recursivo(sub["group_by"], valores_vars)
    if sub.get("index"):
        query["indexes"] = [sub["index"]]

    return QuerySpec(
        widget=widget,
        indice_request=indice,
        data_source=data_source,
        response_format=response_format,
        queries=[query],
    )


def nome_metrica(query: str) -> str:
    """Extrai o nome da metrica de uma query classica.

    'avg:aws.rds.cpuutilization{env:prod} by {host}' -> 'aws.rds.cpuutilization'
    Alimenta a categorizacao por namespace.
    """
    if not query:
        return ""
    texto = _PREFIXO_AGG.sub("", query).strip()
    # Corta no primeiro delimitador de escopo/operador.
    for delim in ("{", "(", ",", " ", ")"):
        pos = texto.find(delim)
        if pos > 0:
            texto = texto[:pos]
    return texto.strip()
