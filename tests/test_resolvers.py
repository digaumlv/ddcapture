"""Fase 2b: leitura das respostas das APIs de dados, sem rede."""

from __future__ import annotations

import pytest

from ddcapture.extractor import extrair
from ddcapture.resolvers import metrics as resolver_metrics
from ddcapture.resolvers import monitors as resolver_monitors
from ddcapture.resolvers import slo as resolver_slo
from ddcapture.resolvers import tags_de_lista, unidade_de


class ClienteFalso:
    """Devolve respostas prontas e registra o que foi pedido."""

    def __init__(self, respostas: dict[str, dict]):
        self.respostas = respostas
        self.chamadas: list[tuple[str, str, dict]] = []

    def get(self, caminho, params=None):
        self.chamadas.append(("GET", caminho, params or {}))
        return self.respostas[caminho]

    def post(self, caminho, corpo):
        self.chamadas.append(("POST", caminho, corpo))
        return self.respostas[caminho]


def _spec(por_titulo, valores_vars, titulo):
    return extrair(por_titulo[titulo], valores_vars, "avg")[0]


def test_escalar_le_colunas_de_valor(por_titulo, valores_vars):
    cliente = ClienteFalso(
        {
            "/api/v2/query/scalar": {
                "data": {
                    "attributes": {
                        "columns": [
                            {
                                "name": "mem",
                                "type": "number",
                                "values": [1024.0],
                                "meta": {"unit": [{"short_name": "MB"}]},
                            }
                        ]
                    }
                }
            }
        }
    )

    valores = resolver_metrics.resolver(
        cliente, _spec(por_titulo, valores_vars, "Memoria livre"), 1000, 2000
    )

    assert len(valores) == 1
    assert valores[0].valor == 1024.0
    assert valores[0].unidade == "MB"
    assert valores[0].erro is None


def test_escalar_converte_janela_para_milissegundos(por_titulo, valores_vars):
    cliente = ClienteFalso({"/api/v2/query/scalar": {"data": {"attributes": {"columns": []}}}})
    resolver_metrics.resolver(cliente, _spec(por_titulo, valores_vars, "Memoria livre"), 1000, 2000)

    _, _, corpo = cliente.chamadas[0]
    attrs = corpo["data"]["attributes"]
    assert attrs["from"] == 1_000_000
    assert attrs["to"] == 2_000_000


def test_escalar_cruza_colunas_de_grupo_com_valores(por_titulo, valores_vars):
    """Colunas group e number sao paralelas: a linha liga as duas."""
    cliente = ClienteFalso(
        {
            "/api/v2/query/scalar": {
                "data": {
                    "attributes": {
                        "columns": [
                            {
                                "name": "service",
                                "type": "group",
                                "values": [["service:checkout"], ["service:carrinho"]],
                            },
                            {"name": "erros", "type": "number", "values": [12.0, 5.0]},
                        ]
                    }
                }
            }
        }
    )

    valores = resolver_metrics.resolver(
        cliente, _spec(por_titulo, valores_vars, "Erros 5xx por servico"), 1000, 2000
    )

    assert len(valores) == 2
    assert valores[0].valor == 12.0
    # O escopo fica em tags; quem compoe o nome final e runner._nome_final.
    assert valores[0].tags == {"service": "checkout"}
    assert valores[0].nome == "erros"
    assert valores[1].tags == {"service": "carrinho"}


def test_timeseries_guarda_o_ultimo_ponto_valido(por_titulo, valores_vars):
    cliente = ClienteFalso(
        {
            "/api/v2/query/timeseries": {
                "data": {
                    "attributes": {
                        "series": [
                            {"group_tags": ["host:web-01"], "query_index": 0, "unit": [{"short_name": "%"}]},
                            {"group_tags": ["host:web-02"], "query_index": 0, "unit": [{"short_name": "%"}]},
                        ],
                        "times": [1_700_000_000_000, 1_700_000_060_000],
                        "values": [[10.0, 12.5], [20.0, None]],
                    }
                }
            }
        }
    )

    valores = resolver_metrics.resolver(
        cliente, _spec(por_titulo, valores_vars, "CPU por host"), 1000, 2000
    )

    assert len(valores) == 2
    assert valores[0].valor == 12.5
    assert valores[0].timestamp == 1_700_000_060
    # A segunda serie termina em null: vale o ultimo ponto com valor.
    assert valores[1].valor == 20.0
    assert valores[1].timestamp == 1_700_000_000
    # O alias da formula nomeia o valor.
    assert valores[0].nome.startswith("CPU %")


def test_timeseries_nao_envia_aggregator(por_titulo, valores_vars):
    """A API de timeseries rejeita aggregator dentro da query."""
    cliente = ClienteFalso(
        {"/api/v2/query/timeseries": {"data": {"attributes": {"series": [], "times": [], "values": []}}}}
    )
    spec = _spec(por_titulo, valores_vars, "CPU por host")
    spec.queries[0]["aggregator"] = "avg"  # simula um widget que declarou o campo

    resolver_metrics.resolver(cliente, spec, 1000, 2000)

    _, _, corpo = cliente.chamadas[0]
    assert all("aggregator" not in q for q in corpo["data"]["attributes"]["queries"])


def test_query_legada_usa_v1_com_segundos(por_titulo, valores_vars):
    cliente = ClienteFalso(
        {
            "/api/v1/query": {
                "series": [
                    {
                        "metric": "aws.rds.database_connections",
                        "scope": "env:prod",
                        "pointlist": [[1_700_000_000_000, 42.0]],
                        "unit": [{"short_name": "conn"}],
                    }
                ]
            }
        }
    )

    valores = resolver_metrics.resolver(
        cliente, _spec(por_titulo, valores_vars, "Conexoes RDS"), 1000, 2000
    )

    metodo, caminho, params = cliente.chamadas[0]
    assert (metodo, caminho) == ("GET", "/api/v1/query")
    # v1 usa SEGUNDOS, ao contrario da v2.
    assert params["from"] == 1000 and params["to"] == 2000

    assert valores[0].valor == 42.0
    assert valores[0].timestamp == 1_700_000_000
    assert valores[0].tags == {"env": "prod"}


def test_resposta_vazia_vira_erro_e_nao_excecao(por_titulo, valores_vars):
    cliente = ClienteFalso({"/api/v1/query": {"series": []}})
    valores = resolver_metrics.resolver(
        cliente, _spec(por_titulo, valores_vars, "Conexoes RDS"), 1000, 2000
    )

    assert len(valores) == 1
    assert valores[0].valor is None
    assert "nao retornou" in valores[0].erro


def test_slo_captura_sli_alvo_e_budget(por_titulo, valores_vars):
    cliente = ClienteFalso(
        {
            "/api/v1/slo/slo123abc/history": {
                "data": {
                    "slo": {"name": "Checkout disponivel"},
                    "overall": {
                        "sli_value": 99.87,
                        "target": 99.9,
                        "error_budget_remaining": -12.5,
                    },
                }
            }
        }
    )

    valores = resolver_slo.resolver(
        cliente, _spec(por_titulo, valores_vars, "SLO de checkout"), 1000, 2000
    )

    por_nome = {v.nome: v.valor for v in valores}
    assert por_nome["Checkout disponivel - SLI"] == 99.87
    assert por_nome["Checkout disponivel - alvo"] == 99.9
    assert por_nome["Checkout disponivel - error budget restante"] == -12.5

    _, _, params = cliente.chamadas[0]
    assert params == {"from_ts": 1000, "to_ts": 2000}


def test_monitores_contam_por_estado(por_titulo, valores_vars):
    cliente = ClienteFalso(
        {
            "/api/v1/monitor": [
                {"overall_state": "OK"},
                {"overall_state": "OK"},
                {"overall_state": "Alert"},
                {"overall_state": "No Data"},
            ]
        }
    )

    valores = resolver_monitors.resolver(
        cliente, _spec(por_titulo, valores_vars, "Monitores da plataforma"), 1000, 2000
    )

    por_nome = {v.nome: v.valor for v in valores}
    assert por_nome["Monitores da plataforma - Alert"] == 1.0
    assert por_nome["Monitores da plataforma - OK"] == 2.0
    assert por_nome["Monitores da plataforma - total"] == 4.0
    # Alert vem antes de OK: a ordem segue a severidade.
    assert valores[0].tags["estado"] == "Alert"


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ([{"short_name": "MB"}], "MB"),
        ([{"short_name": "req"}, {"short_name": "s"}], "req/s"),
        ({"name": "byte"}, "byte"),
        (None, None),
        ([], None),
    ],
)
def test_unidade_de(entrada, esperado):
    assert unidade_de(entrada) == esperado


def test_tags_de_lista():
    assert tags_de_lista(["host:web-01", "env:prod"]) == {"host": "web-01", "env": "prod"}
    # Tag sem ':' e valida no Datadog - vira chave com valor vazio.
    assert tags_de_lista(["producao"]) == {"producao": ""}
    assert tags_de_lista(None) == {}
