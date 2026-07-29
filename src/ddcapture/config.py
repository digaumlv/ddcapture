"""Carga de configuracao: .env para segredos, YAML para o resto."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Sites validos do Datadog. O host da API e sempre api.<site>.
SITES_VALIDOS = frozenset(
    {
        "datadoghq.com",
        "datadoghq.eu",
        "us3.datadoghq.com",
        "us5.datadoghq.com",
        "ap1.datadoghq.com",
        "ap2.datadoghq.com",
        "ddog-gov.com",
    }
)

# O '-' e opcional: uma janela e sempre para tras, entao '15m' == '-15m'.
# Aceitar as duas formas evita o tropeco do argparse, que le '-15m' como flag.
_RELATIVO = re.compile(r"^-?(\d+)([smhdw])$")

# Data brasileira: dia/mes[/ano] [hora:min[:seg]]. O ano e opcional (assume o
# corrente) e a ordem e SEMPRE dia/mes - '01/07' e 1 de julho, nao 7 de janeiro.
_DATA_BR = re.compile(
    r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"
    r"(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)

# Data ISO: ano-mes-dia [hora:min[:seg]].
_DATA_ISO = re.compile(
    r"^(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[ t](\d{1,2}):(\d{2})(?::(\d{2}))?)?$"
)
_SEGUNDOS_POR_UNIDADE = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


class ErroConfig(Exception):
    """Configuracao ausente ou invalida."""


@dataclass
class Credenciais:
    api_key: str
    app_key: str
    site: str

    @property
    def base_url(self) -> str:
        return f"https://api.{self.site}"


@dataclass
class Config:
    credenciais: Credenciais | None
    dashboard_id: str
    janela_from: str
    janela_to: str
    agregador_padrao: str
    saida_dir: Path
    sinks: dict[str, bool]
    sqlite_arquivo: str
    http_timeout_s: int
    http_max_tentativas: int
    http_backoff_base_s: float
    categorias: dict[str, Any] = field(default_factory=dict)

    @property
    def tags_dimensao(self) -> list[str]:
        return list(self.categorias.get("tags_dimensao") or [])


def resolver_instante(
    valor: str,
    agora: int | None = None,
    fim_do_dia: bool = False,
) -> int:
    """Converte a janela informada em epoch de segundos.

    Aceita:
        relativo   -1h, -30m, 15m, -7d      (o '-' e opcional)
        data BR    01/07, 01/07/2026, 01/07/2026 08:30
        data ISO   2026-07-01, 2026-07-01 08:30
        agora      now
        epoch      1700000000 (s) ou 1700000000000 (ms, como vem da URL do Datadog)

    Datas sao lidas no fuso LOCAL da maquina - quem escreve '01/07' pensa no dia
    civil daqui, nao em UTC. A conversao para UTC fica com o .timestamp().

    `fim_do_dia` muda o horario implicito de uma data SEM hora: 00:00:00 vira
    23:59:59. E o que faz '--from 01/07 --to 31/07' incluir o dia 31 inteiro,
    em vez de parar na virada da meia-noite.
    """
    agora = int(time.time()) if agora is None else agora
    valor = str(valor).strip().lower()

    if valor in ("now", "agora", ""):
        return agora

    m = _RELATIVO.match(valor)
    if m:
        quantidade, unidade = int(m.group(1)), m.group(2)
        return agora - quantidade * _SEGUNDOS_POR_UNIDADE[unidade]

    m = _DATA_BR.match(valor)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        ano = _ano_completo(m.group(3), agora)
        return _epoch_local(ano, mes, dia, m.group(4), m.group(5), m.group(6), fim_do_dia, valor)

    m = _DATA_ISO.match(valor)
    if m:
        ano, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _epoch_local(ano, mes, dia, m.group(4), m.group(5), m.group(6), fim_do_dia, valor)

    if valor.lstrip("-").isdigit():
        n = int(valor)
        # 13 digitos = milissegundos.
        return n // 1000 if len(str(abs(n))) >= 13 else n

    raise ErroConfig(
        f"Instante invalido: {valor!r}. Use '-1h', '01/07', '01/07/2026', "
        "'2026-07-01', 'now' ou um epoch."
    )


def _ano_completo(ano: str | None, agora: int) -> int:
    """Ano ausente = o ano corrente; dois digitos = 20xx."""
    if not ano:
        return datetime.fromtimestamp(agora).year
    n = int(ano)
    return 2000 + n if n < 100 else n


def _epoch_local(
    ano: int,
    mes: int,
    dia: int,
    hora: str | None,
    minuto: str | None,
    segundo: str | None,
    fim_do_dia: bool,
    original: str,
) -> int:
    if hora is None and fim_do_dia:
        h, mi, s = 23, 59, 59
    else:
        h, mi, s = int(hora or 0), int(minuto or 0), int(segundo or 0)

    try:
        # Naive de proposito: .timestamp() interpreta no fuso local da maquina.
        return int(datetime(ano, mes, dia, h, mi, s).timestamp())
    except ValueError as exc:
        raise ErroConfig(
            f"Data invalida: {original!r} ({exc}). O formato brasileiro e dia/mes."
        ) from exc


def _raiz_projeto() -> Path:
    # src/ddcapture/config.py -> raiz do projeto
    return Path(__file__).resolve().parents[2]


def carregar_credenciais() -> Credenciais:
    """Le as credenciais do ambiente. Levanta ErroConfig se faltar alguma."""
    load_dotenv(_raiz_projeto() / ".env")

    api_key = os.getenv("DD_API_KEY", "").strip()
    app_key = os.getenv("DD_APP_KEY", "").strip()
    site = os.getenv("DD_SITE", "datadoghq.com").strip()

    faltando = [n for n, v in (("DD_API_KEY", api_key), ("DD_APP_KEY", app_key)) if not v]
    if faltando:
        raise ErroConfig(
            f"Variaveis ausentes: {', '.join(faltando)}. "
            "Copie .env.example para .env e preencha."
        )
    if site not in SITES_VALIDOS:
        raise ErroConfig(
            f"DD_SITE invalido: {site!r}. Validos: {', '.join(sorted(SITES_VALIDOS))}"
        )
    return Credenciais(api_key=api_key, app_key=app_key, site=site)


def carregar(
    config_dir: Path | None = None,
    *,
    exigir_credenciais: bool = True,
) -> Config:
    """Monta a Config a partir dos YAMLs e do ambiente.

    Com exigir_credenciais=False a Config vem sem credenciais - util para testes
    e para inspecionar um dashboard salvo em arquivo.
    """
    config_dir = config_dir or (_raiz_projeto() / "config")

    settings = _ler_yaml(config_dir / "settings.yaml")
    # settings.local.yaml e opcional e fica fora do versionamento: e onde vao
    # os valores desta instalacao (dashboard_id, janela) sem virar commit.
    settings = _mesclar(settings, _ler_yaml(config_dir / "settings.local.yaml", opcional=True))
    categorias = _ler_yaml(config_dir / "categorias.yaml")

    credenciais = None
    if exigir_credenciais:
        credenciais = carregar_credenciais()

    janela = settings.get("janela") or {}
    http = settings.get("http") or {}
    saida_dir = Path(settings.get("saida_dir") or "out")
    if not saida_dir.is_absolute():
        saida_dir = _raiz_projeto() / saida_dir

    return Config(
        credenciais=credenciais,
        dashboard_id=str(settings.get("dashboard_id") or ""),
        janela_from=str(janela.get("from") or "-1h"),
        janela_to=str(janela.get("to") or "now"),
        agregador_padrao=str(settings.get("agregador_padrao") or "avg"),
        saida_dir=saida_dir,
        sinks=dict(settings.get("sinks") or {}),
        sqlite_arquivo=str(settings.get("sqlite_arquivo") or "capturas.sqlite"),
        http_timeout_s=int(http.get("timeout_s") or 30),
        http_max_tentativas=int(http.get("max_tentativas") or 5),
        http_backoff_base_s=float(http.get("backoff_base_s") or 1.0),
        categorias=categorias,
    )


def _ler_yaml(caminho: Path, opcional: bool = False) -> dict[str, Any]:
    if not caminho.exists():
        if opcional:
            return {}
        raise ErroConfig(f"Arquivo de configuracao nao encontrado: {caminho}")
    with caminho.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _mesclar(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Sobrepoe `override` em `base`, descendo nos dicionarios aninhados.

    Raso demais quebraria `janela` e `sinks`: declarar so `janela.from` no
    arquivo local apagaria o `to` do settings.yaml.
    """
    saida = dict(base)
    for chave, valor in (override or {}).items():
        atual = saida.get(chave)
        if isinstance(atual, dict) and isinstance(valor, dict):
            saida[chave] = _mesclar(atual, valor)
        else:
            saida[chave] = valor
    return saida
