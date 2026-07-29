"""Widgets alimentados por dataset (celula de notebook).

A query e identificada por dataset_id + dataset_provider. Descartar qualquer
um dos dois faz a API responder 'Invalid query input' - o widget vira falha
mesmo tendo dado.
"""

from __future__ import annotations

import pytest

from ddcapture.extractor import extrair
from ddcapture.models import Widget

# Base64 ficticio, no mesmo formato que a API usa (notebook_cell:<uuid>).
DATASET_ID = "MW5vdGVib29rX2NlbGw6MDAwMDAwMDA"


@pytest.fixture
def spec():
    definition = {
        "type": "query_value",
        "title": "Total de reenvios",
        "requests": [
            {
                "formulas": [{"formula": "query1"}],
                "queries": [
                    {
                        "data_source": "dataset",
                        "dataset_provider": "notebook_cell",
                        "name": "query1",
                        "dataset_id": DATASET_ID,
                        "compute": [
                            {
                                "column": "total_reenvios",
                                "aggregation": "sum",
                                "name": "sum:total_reenvios",
                            }
                        ],
                        "query_filter": "",
                        "sort": [{"aggregation": "count", "order": "desc"}],
                    }
                ],
                "response_format": "scalar",
            }
        ],
    }
    widget = Widget(
        widget_id="6971009279062902",
        tipo="query_value",
        titulo="Total de reenvios",
        grupo_pai="Geral",
        definition=definition,
    )
    return extrair(widget, {}, "avg")[0]


def test_identificadores_do_dataset_sobrevivem(spec):
    """Sem estes dois campos a API nao sabe qual dataset consultar."""
    q = spec.queries[0]
    assert q["dataset_id"] == DATASET_ID
    assert q["dataset_provider"] == "notebook_cell"


def test_compute_do_dataset_e_uma_lista(spec):
    """Diferente de logs, onde compute e um dict unico."""
    compute = spec.queries[0]["compute"]
    assert isinstance(compute, list)
    assert compute[0]["column"] == "total_reenvios"
    assert compute[0]["aggregation"] == "sum"


def test_query_filter_e_sort_passam(spec):
    q = spec.queries[0]
    assert q["query_filter"] == ""
    assert q["sort"] == [{"aggregation": "count", "order": "desc"}]


def test_dataset_nao_recebe_aggregator(spec):
    """aggregator so vale para metricas - aqui a agregacao esta no compute."""
    assert "aggregator" not in spec.queries[0]


def test_formula_referencia_o_nome_da_query(spec):
    """Usar o nome do compute ('sum:total_reenvios') quebra o parser da API."""
    assert spec.formulas == [{"formula": "query1"}]


def test_data_source_e_response_format(spec):
    assert spec.data_source == "dataset"
    assert spec.response_format == "scalar"
