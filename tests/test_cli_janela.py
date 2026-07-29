"""Janelas de tempo na linha de comando.

'--from -15m' e a invocacao natural, mas o argparse le '-15m' como flag.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ddcapture.cli import _normalizar_argv, montar_parser
from ddcapture.config import ErroConfig, resolver_instante

AGORA = 1_700_000_000


@pytest.mark.parametrize(
    "argv,esperado",
    [
        (["--from", "-15m"], ["--from=-15m"]),
        (["--to", "-1h"], ["--to=-1h"]),
        (["--from", "-7d", "--to", "-1d"], ["--from=-7d", "--to=-1d"]),
        # Sem hifen tambem e colado; '--from=15m' parseia igual a '--from 15m'.
        (["--from", "15m"], ["--from=15m"]),
        # Epoch nao casa o padrao relativo.
        (["--from", "1700000000"], ["--from", "1700000000"]),
        # Outras flags passam intactas.
        (["--dashboard-id", "abc", "--dry-run"], ["--dashboard-id", "abc", "--dry-run"]),
        # '--from' no fim, sem valor: deixa o argparse reclamar.
        (["--from"], ["--from"]),
    ],
)
def test_normalizar_argv(argv, esperado):
    assert _normalizar_argv(argv) == esperado


def test_parser_aceita_from_com_hifen():
    args = montar_parser().parse_args(_normalizar_argv(["--from", "-15m"]))
    assert args.inicio == "-15m"


@pytest.mark.parametrize("valor", ["-15m", "15m"])
def test_relativo_com_e_sem_hifen_sao_iguais(valor):
    """Uma janela e sempre para tras: '15m' e '-15m' significam o mesmo."""
    assert resolver_instante(valor, agora=AGORA) == AGORA - 900


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("-1h", AGORA - 3600),
        ("-1d", AGORA - 86400),
        ("-7d", AGORA - 604800),
        ("now", AGORA),
        ("1699999000", 1699999000),
        # 13 digitos = milissegundos, convertido para segundos.
        ("1700000000000", 1700000000),
    ],
)
def test_resolver_instante(valor, esperado):
    assert resolver_instante(valor, agora=AGORA) == esperado


def test_instante_invalido_e_reportado():
    with pytest.raises(ErroConfig, match="Instante invalido"):
        resolver_instante("ontem", agora=AGORA)


# --- Datas --------------------------------------------------------------

# 2026-07-15 12:00:00 local - so serve para definir o ano corrente.
AGORA_2026 = int(datetime(2026, 7, 15, 12, 0, 0).timestamp())


def _local(ano, mes, dia, h=0, mi=0, s=0) -> int:
    """Epoch do instante no fuso LOCAL - e assim que datas sao interpretadas."""
    return int(datetime(ano, mes, dia, h, mi, s).timestamp())


@pytest.mark.parametrize(
    "valor,esperado",
    [
        # Ano omitido = ano corrente.
        ("01/07", _local(2026, 7, 1)),
        ("31/07", _local(2026, 7, 31)),
        ("01/07/2026", _local(2026, 7, 1)),
        # Ano de dois digitos.
        ("01/07/26", _local(2026, 7, 1)),
        # Com hora.
        ("01/07 08:30", _local(2026, 7, 1, 8, 30)),
        ("01/07/2026 08:30:15", _local(2026, 7, 1, 8, 30, 15)),
        # ISO.
        ("2026-07-01", _local(2026, 7, 1)),
        ("2026-07-01 08:30", _local(2026, 7, 1, 8, 30)),
    ],
)
def test_datas(valor, esperado):
    assert resolver_instante(valor, agora=AGORA_2026) == esperado


def test_formato_e_dia_barra_mes_nao_mes_barra_dia():
    """'01/07' e 1 de julho. Ler como 7 de janeiro erraria a janela em meses."""
    assert resolver_instante("01/07", agora=AGORA_2026) == _local(2026, 7, 1)
    # 13 nao existe como mes, entao so pode ser dia 13 de julho.
    assert resolver_instante("13/07", agora=AGORA_2026) == _local(2026, 7, 13)


def test_data_sem_hora_no_to_cobre_o_dia_inteiro():
    """Sem isso, '--to 31/07' pararia na virada e perderia o dia 31."""
    inicio = resolver_instante("31/07", agora=AGORA_2026)
    fim = resolver_instante("31/07", agora=AGORA_2026, fim_do_dia=True)

    assert inicio == _local(2026, 7, 31, 0, 0, 0)
    assert fim == _local(2026, 7, 31, 23, 59, 59)


def test_hora_explicita_ignora_fim_do_dia():
    """Quem escreveu a hora quer aquela hora, nao 23:59."""
    assert resolver_instante(
        "31/07 18:00", agora=AGORA_2026, fim_do_dia=True
    ) == _local(2026, 7, 31, 18, 0)


def test_janela_de_julho_inteira():
    inicio = resolver_instante("01/07", agora=AGORA_2026)
    fim = resolver_instante("31/07", agora=AGORA_2026, fim_do_dia=True)

    assert inicio < fim
    # 31 dias completos, menos o segundo que falta para a meia-noite.
    assert fim - inicio == 31 * 86400 - 1


@pytest.mark.parametrize("valor", ["32/07", "01/13", "30/02", "2026-13-01"])
def test_data_impossivel_e_reportada(valor):
    with pytest.raises(ErroConfig, match="Data invalida|Instante invalido"):
        resolver_instante(valor, agora=AGORA_2026)


def test_data_passa_pelo_normalizador_do_argv():
    """Datas nao comecam com '-', entao o argparse ja da conta."""
    args = montar_parser().parse_args(
        _normalizar_argv(["--from", "01/07", "--to", "31/07"])
    )
    assert args.inicio == "01/07"
    assert args.fim == "31/07"
