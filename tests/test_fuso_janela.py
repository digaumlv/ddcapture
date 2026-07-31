"""Fuso em que as datas da janela sao lidas.

O fuso desloca a janela inteira. Lendo '01/06' no fuso local de UTC-3, a
janela do mes comeca as 03:00 UTC de 01/06 e termina as 02:59 UTC de 01/07 -
perde as 3 primeiras horas de junho e ganha as 3 primeiras de julho.
Para fechamento por competencia isso e erro.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ddcapture.config import Config, resolver_instante

AGORA = int(datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp())


def _utc(ano, mes, dia, h=0, mi=0, s=0) -> int:
    return int(datetime(ano, mes, dia, h, mi, s, tzinfo=timezone.utc).timestamp())


def test_data_em_utc_fecha_o_mes_exato():
    inicio = resolver_instante("01/06/2026", agora=AGORA, utc=True)
    fim = resolver_instante("30/06/2026", agora=AGORA, fim_do_dia=True, utc=True)

    assert inicio == _utc(2026, 6, 1, 0, 0, 0)
    assert fim == _utc(2026, 6, 30, 23, 59, 59)


def test_janela_utc_nao_invade_o_mes_seguinte():
    """O caso concreto: nada de julho pode entrar numa janela de junho."""
    fim = resolver_instante("30/06/2026", agora=AGORA, fim_do_dia=True, utc=True)
    primeiro_de_julho = _utc(2026, 7, 1, 0, 0, 0)

    assert fim < primeiro_de_julho
    assert primeiro_de_julho - fim == 1  # fecha 1s antes da virada


def test_junho_em_utc_tem_30_dias_exatos():
    inicio = resolver_instante("01/06/2026", agora=AGORA, utc=True)
    fim = resolver_instante("30/06/2026", agora=AGORA, fim_do_dia=True, utc=True)

    assert fim - inicio == 30 * 86400 - 1


def test_local_e_utc_diferem_pelo_offset():
    local = resolver_instante("01/06/2026", agora=AGORA, utc=False)
    utc = resolver_instante("01/06/2026", agora=AGORA, utc=True)

    offset = local - utc
    # A diferenca e exatamente o offset do fuso da maquina, em horas cheias
    # ou meias horas - nunca um valor arbitrario.
    assert offset % 1800 == 0


def test_relativo_ignora_o_fuso():
    """'-1h' e ancorado em `agora`; fuso nao entra na conta."""
    assert (
        resolver_instante("-1h", agora=AGORA, utc=True)
        == resolver_instante("-1h", agora=AGORA, utc=False)
        == AGORA - 3600
    )


def test_epoch_ignora_o_fuso():
    assert (
        resolver_instante("1700000000", agora=AGORA, utc=True)
        == resolver_instante("1700000000", agora=AGORA, utc=False)
        == 1700000000
    )


def test_hora_explicita_respeita_o_fuso():
    assert resolver_instante("15/06/2026 08:30", agora=AGORA, utc=True) == _utc(
        2026, 6, 15, 8, 30
    )


@pytest.mark.parametrize(
    "valor,esperado",
    [("utc", True), ("UTC", True), (" utc ", True), ("local", False), ("", False)],
)
def test_config_interpreta_o_fuso(valor, esperado):
    cfg = Config(
        credenciais=None,
        dashboard_id="",
        janela_from="-1h",
        janela_to="now",
        agregador_padrao="avg",
        saida_dir=__import__("pathlib").Path("out"),
        sinks={},
        sqlite_arquivo="x.sqlite",
        http_timeout_s=30,
        http_max_tentativas=5,
        http_backoff_base_s=1.0,
        fuso=valor,
    )
    assert cfg.janela_em_utc is esperado


def test_fuso_padrao_e_local():
    """Mudar o padrao deslocaria em silencio toda janela ja em uso."""
    cfg = Config(
        credenciais=None,
        dashboard_id="",
        janela_from="-1h",
        janela_to="now",
        agregador_padrao="avg",
        saida_dir=__import__("pathlib").Path("out"),
        sinks={},
        sqlite_arquivo="x.sqlite",
        http_timeout_s=30,
        http_max_tentativas=5,
        http_backoff_base_s=1.0,
    )
    assert cfg.janela_em_utc is False
