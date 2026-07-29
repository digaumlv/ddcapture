"""Fase 2a: extracao de queries nos formatos moderno e legado."""

from __future__ import annotations

from ddcapture.extractor import extrair, nome_metrica


def _specs(widget, valores_vars, agregador="avg"):
    return extrair(widget, valores_vars, agregador)


def test_formato_moderno_preserva_queries_e_formulas(por_titulo, valores_vars):
    specs = _specs(por_titulo["CPU por host"], valores_vars)
    assert len(specs) == 1

    spec = specs[0]
    assert spec.data_source == "metrics"
    assert spec.response_format == "timeseries"
    assert spec.queries[0]["name"] == "cpu"
    # A template variable foi resolvida.
    assert spec.queries[0]["query"] == "avg:system.cpu.user{env:prod} by {host}"
    assert spec.formulas == [{"formula": "cpu", "alias": "CPU %"}]


def test_formulas_perdem_campos_de_estilo(por_titulo, valores_vars):
    spec = _specs(por_titulo["CPU por host"], valores_vars)[0]
    # A API de query rejeita 'style' dentro da formula.
    assert all(set(f) <= {"formula", "alias"} for f in spec.formulas)


def test_query_value_usa_agregador_last(por_titulo, valores_vars):
    spec = _specs(por_titulo["Memoria livre"], valores_vars)[0]
    assert spec.response_format == "scalar"
    # query_value mostra o ultimo ponto, nao a media da janela.
    assert spec.queries[0]["aggregator"] == "last"


def test_timeseries_nao_recebe_agregador(por_titulo, valores_vars):
    spec = _specs(por_titulo["CPU por host"], valores_vars)[0]
    assert "aggregator" not in spec.queries[0]


def test_agregador_do_widget_vence_o_padrao(por_titulo, valores_vars):
    spec = _specs(por_titulo["Erros 5xx por servico"], valores_vars, agregador="avg")[0]
    # A query declara sum; o padrao avg nao deve sobrescrever.
    assert spec.queries[0]["aggregator"] == "sum"


def test_formato_legado_vira_query_legada(por_titulo, valores_vars):
    spec = _specs(por_titulo["Conexoes RDS"], valores_vars)[0]
    assert spec.e_legada is True
    assert spec.queries == []
    assert spec.query_legada == "avg:aws.rds.database_connections{env:prod}"


def test_widget_de_slo_extrai_o_id(por_titulo, valores_vars):
    spec = _specs(por_titulo["SLO de checkout"], valores_vars)[0]
    assert spec.data_source == "slo"
    assert spec.extra["slo_id"] == "slo123abc"


def test_widget_de_monitor_extrai_a_busca(por_titulo, valores_vars):
    spec = _specs(por_titulo["Monitores da plataforma"], valores_vars)[0]
    assert spec.data_source == "monitors"
    assert spec.extra["query"] == "tag:team-plataforma"


def test_widget_de_logs_mantem_search_e_compute(por_titulo, valores_vars):
    spec = _specs(por_titulo["Volume de logs de erro"], valores_vars)[0]
    assert spec.data_source == "logs"

    q = spec.queries[0]
    # A variavel tambem e resolvida dentro do search.
    assert q["search"]["query"] == "status:error env:prod"
    assert q["compute"]["aggregation"] == "count"
    assert q["group_by"][0]["facet"] == "service"
    # Consulta de logs nao leva aggregator de metrica.
    assert "aggregator" not in q


def test_widget_sem_dado_nao_gera_query(widgets, valores_vars):
    nota = next(w for w in widgets if w.tipo == "note")
    assert _specs(nota, valores_vars) == []


def test_descricao_query_cobre_os_dois_formatos(por_titulo, valores_vars):
    moderno = _specs(por_titulo["Memoria livre"], valores_vars)[0]
    legado = _specs(por_titulo["Conexoes RDS"], valores_vars)[0]

    assert "system.mem.free" in moderno.descricao_query()
    assert "aws.rds.database_connections" in legado.descricao_query()


def test_nome_metrica():
    assert nome_metrica("avg:system.cpu.user{env:prod} by {host}") == "system.cpu.user"
    assert nome_metrica("sum:aws.rds.connections{*}") == "aws.rds.connections"
    # Sem prefixo de agregacao.
    assert nome_metrica("trace.servlet.request{*}") == "trace.servlet.request"
    assert nome_metrica("") == ""
