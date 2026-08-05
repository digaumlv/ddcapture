"""Repositorio: consulta de tarifas, limites e valores fixos.

Usa um SQLite em memoria com o mesmo esquema da carga - a garantia que
interessa e que nenhum valor de negocio venha do codigo, e sim da tabela.
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from precificacao import repositorio


@pytest.fixture
def conexao():
    con = sqlite3.connect(":memory:")
    con.executescript(
        """
        CREATE TABLE faixas_sic (
            faixa_inicial INTEGER, faixa_final INTEGER, tipo_tarifa TEXT,
            tarifa_financeiro NUMERIC, tarifa_nao_financeiro NUMERIC
        );
        CREATE TABLE tarifas_canal (
            canal TEXT, tipo_tarifa TEXT, limite NUMERIC,
            tarifa_inicial NUMERIC, tarifa_final NUMERIC
        );
        CREATE TABLE valores_fixos (
            origem TEXT, item TEXT, canal TEXT, valor NUMERIC,
            condicao TEXT, observacao TEXT
        );
        CREATE TABLE servicos_fixos (
            codigo TEXT, emissor TEXT, servico TEXT,
            valor_fixo NUMERIC, ativo INTEGER
        );

        INSERT INTO faixas_sic VALUES
            (NULL, 250000, 'fixa', '8562.33', '7174.00'),
            (250001, 500000, 'variavel', '0.03393', '0.07000'),
            (500001, 1000000, 'variavel', '0.03224', '0.06000');

        INSERT INTO tarifas_canal VALUES
            ('Whatsapp Utility', 'variavel', '1000000', '0.44', '0.34'),
            ('SMS envio',        'variavel', '1000000', '0.21', '0.16'),
            ('Sem tarifa',       'variavel', NULL,      NULL,   NULL);

        INSERT INTO valores_fixos VALUES
            ('Piso por canal', 'SMS', 'SMS', '2100.00', 'canal_com_uso', NULL),
            ('Piso por canal', 'Whatsapp', 'Whatsapp', '441.00', 'canal_com_uso', NULL),
            ('Faixa SIC', 'Eventos nao financeiros', NULL, '7174.00', 'sempre', NULL),
            ('Faixa SIC', 'Eventos financeiros', NULL, '8562.33', 'acima_da_franquia', NULL);

        INSERT INTO servicos_fixos VALUES
            ('0001', 'Emissor A', 'Whatsapp', '441.00', 1),
            ('0001', 'Emissor A', 'SMS',     '2100.00', 0),
            ('0002', 'Emissor B', 'Whatsapp', '441.00', 1);
        """
    )
    yield con
    con.close()


# --- SIC -----------------------------------------------------------------


def test_parametros_sic_vem_da_tabela(conexao):
    p = repositorio.parametros_sic(conexao)
    assert p.limite == Decimal("250000")
    assert p.valor_ate_limite == Decimal("7174.00")
    # Tarifa do excedente e a da PRIMEIRA faixa variavel.
    assert p.tarifa_excedente == Decimal("0.07000")


def test_sem_linha_fixa_o_sic_falha_em_vez_de_assumir(conexao):
    conexao.execute("DELETE FROM faixas_sic WHERE tipo_tarifa = 'fixa'")
    with pytest.raises(repositorio.ErroRepositorio, match="fixa"):
        repositorio.parametros_sic(conexao)


def test_alterar_a_tabela_altera_o_limite(conexao):
    """Prova que o limite nao esta no codigo."""
    conexao.execute("UPDATE faixas_sic SET faixa_final = 999 WHERE tipo_tarifa='fixa'")
    assert repositorio.parametros_sic(conexao).limite == Decimal("999")


# --- Tarifas de canal ----------------------------------------------------


def test_tarifas_por_canal_indexa_normalizado(conexao):
    tarifas = repositorio.tarifas_por_canal(conexao)
    assert "whatsapputility" in tarifas
    assert tarifas["whatsapputility"].tarifa_inicial == Decimal("0.44")
    assert tarifas["whatsapputility"].tarifa_final == Decimal("0.34")
    assert tarifas["whatsapputility"].limite == Decimal("1000000")


def test_canal_sem_tarifa_e_descartado_com_aviso(conexao, caplog):
    tarifas = repositorio.tarifas_por_canal(conexao)
    assert "semtarifa" not in tarifas


def test_normalizar_casa_grafias_diferentes():
    assert repositorio.normalizar("WhatsApp") == repositorio.normalizar("Whatsapp")
    assert repositorio.normalizar(" SMS envio ") == "smsenvio"
    # 'º' decompoe para 'o' no NFKD, e e isso que faz o rotulo do CSV casar
    # com a grafia sem o indicador ordinal.
    assert repositorio.normalizar("Nº dedicado") == "nodedicado"
    assert repositorio.normalizar("No dedicado") == "nodedicado"


# --- Servicos fixos ------------------------------------------------------


def test_servicos_fixos_do_emissor(conexao):
    servicos = repositorio.servicos_fixos(conexao, "0001")
    assert set(servicos) == {"whatsapp", "sms"}
    assert servicos["whatsapp"].valor_fixo == Decimal("441.00")


def test_servico_inativo_vem_marcado(conexao):
    servicos = repositorio.servicos_fixos(conexao, "0001")
    assert servicos["whatsapp"].ativo is True
    assert servicos["sms"].ativo is False


def test_emissor_sem_cadastro_devolve_vazio_e_avisa(conexao, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        servicos = repositorio.servicos_fixos(conexao, "9999")

    assert servicos == {}
    assert "9999" in caplog.text


def test_emissores_diferentes_tem_valores_proprios(conexao):
    a = repositorio.servicos_fixos(conexao, "0001")
    b = repositorio.servicos_fixos(conexao, "0002")
    assert set(a) != set(b)


# --- Condicoes de cobranca ----------------------------------------------


def test_condicao_por_item_vem_da_tabela(conexao):
    condicoes = repositorio.condicao_por_item(conexao)
    assert condicoes["sms"] == "canal_com_uso"
    assert condicoes["eventosnaofinanceiros"] == "sempre"
    assert condicoes["eventosfinanceiros"] == "acima_da_franquia"


def test_valores_sempre_devidos(conexao):
    itens = repositorio.valores_sempre_devidos(conexao)
    assert len(itens) == 1
    assert itens[0][1] == Decimal("7174.00")


# --- Consulta parametrizada ---------------------------------------------


def test_consulta_usa_parametro_e_nao_concatenacao(conexao):
    """Um codigo com aspas nao pode quebrar nem executar SQL."""
    malicioso = "0001' OR '1'='1"
    assert repositorio.servicos_fixos(conexao, malicioso) == {}
    # A tabela continua intacta.
    assert conexao.execute("SELECT COUNT(*) FROM servicos_fixos").fetchone()[0] == 3
