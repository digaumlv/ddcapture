"""O coletor nao pode modificar nada no Datadog.

O guarda roda ANTES da requisicao sair, entao estes testes nao tocam a rede:
uma chamada bloqueada nunca chega a montar a conexao.
"""

from __future__ import annotations

import pytest

from ddcapture.client import DatadogClient, ErroEscritaBloqueada
from ddcapture.config import Credenciais


@pytest.fixture
def client():
    return DatadogClient(
        Credenciais(api_key="fake", app_key="fake", site="datadoghq.com")
    )


@pytest.mark.parametrize(
    "caminho",
    [
        "/api/v1/dashboard",
        "/api/v1/dashboard/abc-def-ghi",
        "/api/v1/query",
        "/api/v1/slo/xyz/history",
        "/api/v1/monitor",
    ],
)
def test_get_e_sempre_permitido(client, caminho):
    client._garantir_leitura("GET", caminho)


@pytest.mark.parametrize(
    "caminho",
    [
        "/api/v2/query/scalar",
        "/api/v2/query/timeseries",
        "/api/v2/logs/analytics/aggregate",
    ],
)
def test_post_permitido_so_nos_endpoints_de_consulta(client, caminho):
    """Esses POST leem dados - o corpo carrega a query, nao uma mudanca."""
    client._garantir_leitura("POST", caminho)


@pytest.mark.parametrize(
    "metodo,caminho",
    [
        ("POST", "/api/v1/dashboard"),          # criaria um dashboard
        ("PUT", "/api/v1/dashboard/abc"),       # sobrescreveria um dashboard
        ("PATCH", "/api/v1/monitor/123"),       # alteraria um monitor
        ("DELETE", "/api/v1/dashboard/abc"),    # apagaria um dashboard
        ("POST", "/api/v1/monitor"),            # criaria um monitor
        ("POST", "/api/v2/logs/config/indexes"),
        ("POST", "/api/v1/series"),             # enviaria metricas
    ],
)
def test_escrita_e_bloqueada(client, metodo, caminho):
    with pytest.raises(ErroEscritaBloqueada, match="somente-leitura"):
        client._garantir_leitura(metodo, caminho)


def test_bloqueio_acontece_antes_da_requisicao(client, monkeypatch):
    """Nem a sessao HTTP e acionada quando a chamada e de escrita."""

    def explodir(*args, **kwargs):
        raise AssertionError("a requisicao NAO deveria ter sido enviada")

    monkeypatch.setattr(client.sessao, "request", explodir)

    with pytest.raises(ErroEscritaBloqueada):
        client._requisitar("DELETE", "/api/v1/dashboard/abc")
