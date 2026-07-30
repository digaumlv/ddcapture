"""Captura filtrada por template variable (--var).

Duas coisas so aparecem quando se passa --var, e as duas falham em silencio:

1. Sem o prefixo declarado na template variable, '--var codigoEmissor=1234'
   vira o token solto '1234' na query. Isso e busca de texto livre, nao filtro
   de facet: a query nao da erro, so devolve o numero errado.

2. Sem o filtro no nome do arquivo, capturas de emissores diferentes so se
   distinguem pelo timestamp.
"""

from __future__ import annotations

import pytest

from ddcapture.runner import preparar
from ddcapture.sinks import prefixo_arquivo

INICIO, FIM = 1_700_000_000, 1_700_003_600


@pytest.fixture
def dashboard_com_prefixo(dashboard):
    """Acrescenta uma variavel com prefix e uma query que a usa."""
    dashboard["template_variables"].append(
        {"name": "codigoEmissor", "prefix": "@org", "default": "*"}
    )
    grupo = dashboard["widgets"][0]["definition"]["widgets"]
    req = grupo[0]["definition"]["requests"][0]
    req["queries"] = [
        {
            "name": "logs_emissor",
            "data_source": "logs",
            "search": {"query": "service:app env:prd $codigoEmissor"},
            "compute": {"aggregation": "count"},
        }
    ]
    req.pop("formulas", None)
    return dashboard


def _query_do_emissor(resultado) -> str:
    spec = next(s for s in resultado.specs if s.data_source == "logs")
    return spec.queries[0]["search"]["query"]


def test_var_vira_filtro_de_facet_com_o_prefixo(dashboard_com_prefixo, config):
    r = preparar(dashboard_com_prefixo, config, INICIO, FIM, {"codigoEmissor": "1234"})

    assert "@org:1234" in _query_do_emissor(r)


def test_var_nao_vira_token_solto(dashboard_com_prefixo, config):
    """'... env:prd 1234' seria busca por texto livre - numero errado."""
    r = preparar(dashboard_com_prefixo, config, INICIO, FIM, {"codigoEmissor": "1234"})
    query = _query_do_emissor(r)

    assert " 1234" not in query.replace("@org:1234", "")


def test_coringa_some_da_query(dashboard_com_prefixo, config):
    """Sem --var, o default '*' nao deve virar '@org:*' nem sobrar solto."""
    r = preparar(dashboard_com_prefixo, config, INICIO, FIM)
    query = _query_do_emissor(r)

    assert "1234" not in query
    assert "$codigoEmissor" not in query


def test_filtros_ficam_no_resultado(dashboard, config):
    r = preparar(dashboard, config, INICIO, FIM, {"codigoEmissor": "5678"})
    assert r.filtros == {"codigoEmissor": "5678"}


def test_nome_do_arquivo_carrega_o_filtro(dashboard, config):
    r = preparar(dashboard, config, INICIO, FIM, {"codigoEmissor": "1234"})
    nome = prefixo_arquivo(r)

    assert "codigoEmissor-1234" in nome
    assert nome.startswith("abc-def-ghi")


def test_nomes_de_emissores_diferentes_nao_colidem(dashboard, config):
    a = prefixo_arquivo(preparar(dashboard, config, INICIO, FIM, {"codigoEmissor": "1234"}))
    b = prefixo_arquivo(preparar(dashboard, config, INICIO, FIM, {"codigoEmissor": "5678"}))

    # Distinguiveis mesmo que o timestamp coincida.
    assert a.replace("1234", "") == b.replace("5678", "")
    assert a != b


def test_sem_filtro_o_nome_fica_como_antes(dashboard, config):
    nome = prefixo_arquivo(preparar(dashboard, config, INICIO, FIM))

    assert nome.startswith("abc-def-ghi_")
    assert "codigoEmissor" not in nome


def test_rotulo_substitui_o_filtro_no_nome(dashboard, config):
    """Um filtro com OR nao serve de nome de arquivo."""
    r = preparar(dashboard, config, INICIO, FIM, {"codigoEmissor": "(1234 OR 234)"})
    r.rotulo = "1234"

    nome = prefixo_arquivo(r)
    assert "_1234_" in nome
    assert "OR" not in nome
    assert "(" not in nome and ")" not in nome


def test_sem_rotulo_o_filtro_ainda_nomeia(dashboard, config):
    r = preparar(dashboard, config, INICIO, FIM, {"codigoEmissor": "5678"})
    assert "codigoEmissor-5678" in prefixo_arquivo(r)
