"""Widgets query_table: compute e group_by moram fora da query.

Sem trazer os dois para dentro da query, a API v2 responde
'Error decoding payload' porque a query chega sem agregacao nenhuma.
"""

from __future__ import annotations

import pytest

from ddcapture.extractor import extrair
from ddcapture.models import Widget


def _widget_tabela(**extra) -> Widget:
    definition = {
        "type": "query_table",
        "title": "Contagem por canal",
        "requests": [
            {
                "request_type": "table",
                "queries": [
                    {
                        "name": "query1",
                        "data_source": "logs",
                        "search": {"query": "service:app env:prd $TipoCanal"},
                        "indexes": [],
                        "storage": "hot",
                    }
                ],
                "rows": {
                    "group_by": [
                        {
                            "name": "groupBy1",
                            "group_keys": [{"query": "query1", "group_key": "@channel"}],
                        },
                        {
                            "name": "groupBy2",
                            "group_keys": [{"query": "query1", "group_key": "@org"}],
                        },
                    ],
                    "sort": {"limit": 500, "columns": [{"column": "column2", "order": "desc"}]},
                },
                "columns": [
                    {
                        "name": "column1",
                        "type": "compute",
                        "compute": {"query": "query1", "aggregation": "count", "filter": ""},
                        "is_hidden": True,
                    },
                    {
                        "name": "column2",
                        "type": "formula",
                        "alias": "Quantidade",
                        "formula": "default_zero(column1)",
                    },
                ],
                **extra,
            }
        ],
    }
    return Widget(
        widget_id="3454893199397205",
        tipo="query_table",
        titulo="Contagem por canal",
        grupo_pai="Geral",
        definition=definition,
    )


@pytest.fixture
def spec():
    return extrair(_widget_tabela(), {"TipoCanal": "*"}, "avg")[0]


def test_compute_vem_das_colunas(spec):
    q = spec.queries[0]
    assert q["compute"] == {"aggregation": "count"}


def test_group_by_vem_das_linhas(spec):
    q = spec.queries[0]
    facets = [g["facet"] for g in q["group_by"]]
    assert facets == ["@channel", "@org"]


def test_limite_e_reduzido_com_varios_group_by(spec):
    """rows.sort.limit e o teto de LINHAS DA TABELA, nao por facet.

    Repassar 500 por facet com dois agrupamentos faz a API responder
    'Invalid query input'. Medido: 200 falha, 100 passa.
    """
    assert all(g["limit"] == 100 for g in spec.queries[0]["group_by"])


def test_limite_e_preservado_com_um_unico_group_by():
    """Com um agrupamento so, 500 e aceito e trunca menos."""
    widget = _widget_tabela()
    rows = widget.definition["requests"][0]["rows"]
    rows["group_by"] = rows["group_by"][:1]

    spec = extrair(widget, {}, "avg")[0]
    assert spec.queries[0]["group_by"] == [{"facet": "@channel", "limit": 500}]


def test_limite_ausente_cai_para_um_padrao():
    widget = _widget_tabela()
    widget.definition["requests"][0]["rows"].pop("sort")

    spec = extrair(widget, {}, "avg")[0]
    assert all(g["limit"] == 10 for g in spec.queries[0]["group_by"])


def test_formula_da_coluna_e_descartada(spec):
    """'default_zero(column1)' referencia a coluna, nao a query.

    Enviar isso quebra: a API resolve formulas por nome de QUERY. Sem formulas,
    _formulas_implicitas monta a correta a partir de 'query1'.
    """
    assert spec.formulas == []


def test_search_preserva_a_substituicao_de_variaveis(spec):
    assert "$TipoCanal" not in spec.queries[0]["search"]["query"]


def test_data_source_e_response_format(spec):
    assert spec.data_source == "logs"
    assert spec.response_format == "scalar"


def test_query_que_ja_traz_compute_nao_e_sobrescrita():
    """So preenchemos o que falta - nao mexemos no que o widget ja definiu."""
    widget = _widget_tabela()
    widget.definition["requests"][0]["queries"][0]["compute"] = {"aggregation": "cardinality"}

    spec = extrair(widget, {}, "avg")[0]
    assert spec.queries[0]["compute"] == {"aggregation": "cardinality"}
