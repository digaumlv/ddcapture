"""As tres regras de calculo, isoladas de banco e de rede.

Limites e tarifas chegam por parametro: nenhum valor de negocio esta escrito
no modulo de calculo, e por isso estes testes precisam declara-los.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from precificacao import calculo

# Valores usados nos exemplos - vindos de fora, como em producao.
LIMITE_SIC = Decimal("250000")
VALOR_SIC = Decimal("7174.00")
LIMITE_VAR = Decimal("1000000")


# --- Regra 1: SIC --------------------------------------------------------


def test_sic_dentro_do_limite_cobra_o_valor_fixo():
    m = calculo.calcular_sic(200_000, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))
    assert m.valor == Decimal("7174.00")


def test_sic_exatamente_no_limite_ainda_e_fixo():
    """O limite e inclusivo: 250.000 nao gera excedente."""
    m = calculo.calcular_sic(LIMITE_SIC, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))
    assert m.valor == Decimal("7174.00")


def test_sic_acima_do_limite_e_progressivo():
    """Exemplo do enunciado: 300.000 eventos, tarifa 0,05."""
    m = calculo.calcular_sic(300_000, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))
    # 50.000 excedentes x 0,05 = 2.500 + 7.174 = 9.674
    assert m.valor == Decimal("9674.00")


def test_sic_cobra_so_o_excedente_nao_o_total():
    """Se cobrasse o volume inteiro, 300.000 x 0,05 daria 15.000."""
    m = calculo.calcular_sic(300_000, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))
    assert m.valor < Decimal("15000")


def test_sic_um_evento_acima_do_limite():
    m = calculo.calcular_sic(250_001, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))
    assert m.valor == Decimal("7174.05")


def test_sic_sem_tarifa_do_excedente_falha_so_quando_ha_excedente():
    """Dentro do limite a tarifa nao e usada - exigi-la recusaria o registro."""
    m = calculo.calcular_sic(100_000, LIMITE_SIC, VALOR_SIC, None)
    assert m.valor == Decimal("7174.00")

    with pytest.raises(calculo.ErroCalculo, match="tarifa"):
        calculo.calcular_sic(300_000, LIMITE_SIC, VALOR_SIC, None)


def test_sic_quantidade_negativa_e_erro():
    with pytest.raises(calculo.ErroCalculo, match="negativa"):
        calculo.calcular_sic(-1, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))


def test_sic_quantidade_ausente_e_erro():
    with pytest.raises(calculo.ErroCalculo, match="ausente"):
        calculo.calcular_sic(None, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))


# --- Regra 2: FIXO -------------------------------------------------------


def test_fixo_devolve_o_valor_do_emissor():
    m = calculo.calcular_fixo(Decimal("441.00"), True, "Emissor A", "Whatsapp")
    assert m.valor == Decimal("441.00")


def test_fixo_nao_multiplica_pela_quantidade():
    """A quantidade nem entra na assinatura do metodo - e assinatura, nao
    preco unitario."""
    a = calculo.calcular_fixo(Decimal("441.00"), True, "A", "Whatsapp")
    b = calculo.calcular_fixo(Decimal("441.00"), True, "A", "Whatsapp")
    assert a.valor == b.valor == Decimal("441.00")


def test_fixo_inativo_e_erro_distinto():
    with pytest.raises(calculo.ErroCalculo, match="inativo"):
        calculo.calcular_fixo(Decimal("441.00"), False, "A", "Whatsapp")


def test_fixo_sem_valor_nao_vira_zero():
    """Zero e valor financeiro legitimo: mascararia o cadastro faltando."""
    with pytest.raises(calculo.ErroCalculo, match="ausente"):
        calculo.calcular_fixo(None, True, "A", "Whatsapp")


def test_fixo_negativo_e_erro():
    with pytest.raises(calculo.ErroCalculo, match="negativo"):
        calculo.calcular_fixo(Decimal("-1"), True, "A", "Whatsapp")


# --- Regra 3: VARIAVEL ---------------------------------------------------


def test_variavel_dentro_do_limite_usa_a_tarifa_inicial():
    m = calculo.calcular_variavel(
        500_000, LIMITE_VAR, Decimal("0.03"), Decimal("0.02")
    )
    assert m.valor == Decimal("15000.00")


def test_variavel_exatamente_no_limite_ainda_e_tarifa_inicial():
    m = calculo.calcular_variavel(
        LIMITE_VAR, LIMITE_VAR, Decimal("0.03"), Decimal("0.02")
    )
    assert m.valor == Decimal("30000.00")


def test_variavel_acima_do_limite_e_progressivo():
    """Exemplo do enunciado: 1.200.000, tarifas 0,03 e 0,02."""
    m = calculo.calcular_variavel(
        1_200_000, LIMITE_VAR, Decimal("0.03"), Decimal("0.02")
    )
    # 1.000.000 x 0,03 = 30.000  +  200.000 x 0,02 = 4.000
    assert m.valor == Decimal("34000.00")


def test_variavel_nao_rebarateia_o_volume_ja_consumido():
    """Se a tarifa final valesse para tudo, 1.200.000 x 0,02 = 24.000."""
    m = calculo.calcular_variavel(
        1_200_000, LIMITE_VAR, Decimal("0.03"), Decimal("0.02")
    )
    assert m.valor > Decimal("30000")


def test_variavel_sem_tarifa_final_falha_so_acima_do_limite():
    m = calculo.calcular_variavel(500_000, LIMITE_VAR, Decimal("0.03"), None)
    assert m.valor == Decimal("15000.00")

    with pytest.raises(calculo.ErroCalculo, match="tarifa final"):
        calculo.calcular_variavel(1_200_000, LIMITE_VAR, Decimal("0.03"), None)


def test_variavel_sem_tarifa_inicial_e_erro():
    with pytest.raises(calculo.ErroCalculo, match="tarifa inicial"):
        calculo.calcular_variavel(1_000, LIMITE_VAR, None, Decimal("0.02"))


def test_variavel_quantidade_zero_da_zero():
    """Zero calculado e diferente de zero por falta de dado."""
    m = calculo.calcular_variavel(0, LIMITE_VAR, Decimal("0.03"), Decimal("0.02"))
    assert m.valor == Decimal("0.00")


# --- Precisao e arredondamento -------------------------------------------


def test_nao_usa_float_em_nenhuma_etapa():
    m = calculo.calcular_variavel(3, LIMITE_VAR, "0.1", "0.2")
    # Em float, 3 x 0.1 = 0.30000000000000004.
    assert m.valor == Decimal("0.30")


def test_arredonda_half_up_e_nao_banker():
    """round(2.675, 2) nativo devolve 2.67 - errado para valor financeiro."""
    assert calculo.arredondar(Decimal("2.675")) == Decimal("2.68")
    assert calculo.arredondar(Decimal("2.665")) == Decimal("2.67")


def test_arredonda_so_no_fim():
    """As parcelas mantem precisao cheia; so o total e quantizado."""
    m = calculo.calcular_variavel(
        1_000_003, LIMITE_VAR, Decimal("0.001"), Decimal("0.001")
    )
    assert m.valor == Decimal("1000.00")


def test_valor_nao_numerico_e_erro_com_o_campo_no_texto():
    with pytest.raises(calculo.ErroCalculo, match="tarifa inicial"):
        calculo.calcular_variavel(10, LIMITE_VAR, "abc", Decimal("0.02"))


# --- Memoria de calculo --------------------------------------------------


def test_memoria_descreve_a_regra_aplicada():
    m = calculo.calcular_sic(300_000, LIMITE_SIC, VALOR_SIC, Decimal("0.05"))
    assert "progressivo" in m.regra
    assert "fixo" in m.descrever()
    assert "excedente" in m.descrever()


def test_memoria_traz_as_parcelas_somadas():
    m = calculo.calcular_variavel(
        1_200_000, LIMITE_VAR, Decimal("0.03"), Decimal("0.02")
    )
    assert sum(v for _, v in m.parcelas) == Decimal("34000")
