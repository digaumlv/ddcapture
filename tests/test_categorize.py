"""Fase 3: as quatro camadas da cascata de categorizacao."""

from __future__ import annotations

import pytest

from ddcapture.categorize import Categorizador, mesclar_tags, normalizar
from ddcapture.extractor import extrair


@pytest.fixture
def cat(config):
    return Categorizador(config.categorias)


def _spec(widget, valores_vars):
    specs = extrair(widget, valores_vars, "avg")
    assert specs, f"nenhuma query extraida de {widget.titulo!r}"
    return specs[0]


def test_camada_1_grupo_vence_as_demais(cat, por_titulo, valores_vars):
    # O titulo casaria a regra de palavra-chave 'cpu' -> Infraestrutura,
    # mas o grupo do dashboard tem precedencia.
    c = cat.classificar(_spec(por_titulo["CPU por host"], valores_vars))
    assert c.categoria == "Infraestrutura AWS"
    assert c.origem == "grupo"


def test_camada_1_usa_o_grupo_mais_proximo(cat, por_titulo, valores_vars):
    c = cat.classificar(_spec(por_titulo["Conexoes RDS"], valores_vars))
    assert c.categoria == "RDS"
    assert c.origem == "grupo"


def test_camada_2_palavra_chave_sem_grupo(cat, por_titulo, valores_vars):
    c = cat.classificar(_spec(por_titulo["Erros 5xx por servico"], valores_vars))
    assert c.categoria == "Erros"
    assert c.origem == "palavra-chave"


def test_camada_2_ignora_acento(cat, por_titulo, valores_vars):
    # 'Volume de logs de erro' casa 'erro' mesmo com a regra escrita sem acento.
    c = cat.classificar(_spec(por_titulo["Volume de logs de erro"], valores_vars))
    assert c.categoria == "Erros"
    assert c.origem == "palavra-chave"


def test_camada_3_namespace_quando_nao_ha_titulo(cat, por_titulo, valores_vars):
    # Widget sem titulo e sem grupo: sobra o nome da metrica, trace.* -> APM.
    c = cat.classificar(_spec(por_titulo[""], valores_vars))
    assert c.categoria == "APM"
    assert c.origem == "namespace"


def test_camada_4_fallback(cat, por_titulo, valores_vars):
    # 'Painel XPTO' nao casa regra e custom.negocio.* nao tem namespace mapeado.
    c = cat.classificar(_spec(por_titulo["Painel XPTO"], valores_vars))
    assert c.categoria == "sem-categoria"
    assert c.origem == "fallback"


def test_namespace_prefixo_mais_longo_vence(cat, por_titulo, valores_vars):
    """aws.rds precisa vencer aws, senao tudo da AWS cai em 'Cloud'."""
    spec = _spec(por_titulo["Conexoes RDS"], valores_vars)
    # Neutraliza a camada 1 para chegar na camada 3.
    spec.widget.grupo_pai = None
    spec.widget.titulo = "zzz"

    c = cat.classificar(spec)
    assert c.categoria == "Banco de Dados"
    assert c.origem == "namespace"


def test_tags_sao_dimensao_e_nao_categoria(cat, por_titulo, valores_vars):
    tags = cat.extrair_tags(_spec(por_titulo["Memoria livre"], valores_vars))
    assert tags["env"] == "prod"
    # service resolveu para o coringa '*', que nao identifica nada.
    assert "service" not in tags


def test_extrair_tags_do_formato_legado(cat, por_titulo, valores_vars):
    tags = cat.extrair_tags(_spec(por_titulo["Conexoes RDS"], valores_vars))
    assert tags == {"env": "prod"}


def test_extrair_tags_ignora_chaves_fora_da_dimensao(cat, por_titulo, valores_vars):
    # 'by {host}' nao esta em tags_dimensao, entao nao vira coluna.
    tags = cat.extrair_tags(_spec(por_titulo["CPU por host"], valores_vars))
    assert "host" not in tags
    assert tags == {"env": "prod"}


def test_mesclar_tags_serie_vence_escopo():
    resultado = mesclar_tags(
        {"env": "prod", "service": "*"},
        {"service": "checkout", "host": "web-01"},
        ["env", "service", "team"],
    )
    # O valor concreto da serie e mais especifico que o filtro do escopo.
    assert resultado["service"] == "checkout"
    assert resultado["env"] == "prod"
    # host nao esta nas chaves de dimensao.
    assert "host" not in resultado


def test_normalizar_remove_acento_e_caixa():
    assert normalizar("Latência P95") == "latencia p95"
    assert normalizar("MEMÓRIA") == "memoria"
    assert normalizar("") == ""
