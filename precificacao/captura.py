"""Leitura das capturas que o ddcapture ja produziu.

Este modulo NAO captura nada: a logica de captura continua inteira em
src/ddcapture e nos .bat, sem alteracao. Aqui so se le o JSON de saida e se
extrai o que a precificacao precisa - volume por canal e volume de eventos.

O JSON e obrigatorio (e nao o xlsx) porque so ele carrega a query de cada
valor, que e o que permite saber canal e etapa do funil.

Duas armadilhas do dado, tratadas explicitamente:

1. Os nomes de canal REPETEM em cada etapa do funil (REQUEST, SENT, RETSC,
   RETRC, MREAD...). Somar por nome contaria a mesma mensagem varias vezes.

2. As queries usam negacao: '-@log.templateCategory:UTILITY' e WhatsApp SEM
   a categoria Utility. Um regex ingenuo le como se fosse 'com Utility' e
   mistura populacoes complementares.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .configuracao import RAIZ

log = logging.getLogger(__name__)

PASTA_CAPTURAS = RAIZ / "out"

# O codigo do emissor no nome do arquivo: <dashboard>_0000_20260101-000000.json
_CODIGO_ARQUIVO = re.compile(r"_(\d{4})_\d{8}-\d{6}\.json$")

# O '-' na frente inverte o filtro e precisa ser capturado.
_CANAL = re.compile(r"(-?)@log\.messageChannel:([A-Za-z]+)")
_CATEGORIA = re.compile(r"(-?)@log\.templateCategory:([A-Z]+)")
_TIPO = re.compile(r"@type:(\w+)")
_STATUS = re.compile(r"@log\.statusCode:\(?([A-Z]+(?:\s+OR\s+[A-Z]+)*)\)?")

# Widget que lista os canais em uso. E um group_by: canal sem nenhum evento
# nao aparece como grupo, e e isso que define se o canal teve uso.
_WIDGET_CANAIS = re.compile(r"quantidade\s+por\s+canais", re.I)

# Status que representa mensagem efetivamente enviada.
STATUS_FATURAVEL = "SENT"


class ErroCaptura(Exception):
    """Captura ausente ou em formato inesperado."""


@dataclass
class UsoEmissor:
    """O que um emissor consumiu no periodo, ja consolidado."""

    codigo: str
    arquivo: Path
    dashboard: str = ""
    janela: str = ""
    eventos: Decimal = Decimal("0")
    origem_eventos: str = ""
    # canal -> volume enviado
    enviado_por_canal: dict[str, Decimal] = field(default_factory=dict)
    # canal -> volume que prova uso no periodo
    canais_com_uso: dict[str, Decimal] = field(default_factory=dict)


def _classificar(query: str) -> tuple[str | None, str]:
    """Canal e etapa a partir da query do widget."""
    m_canal = _CANAL.search(query)
    if not m_canal:
        return None, ""

    negado, canal = m_canal.group(1), m_canal.group(2)
    if negado:
        canal = f"(exceto {canal})"

    m_cat = _CATEGORIA.search(query)
    if m_cat:
        neg, categoria = m_cat.group(1), m_cat.group(2)
        canal += f" (exceto {categoria})" if neg else f"/{categoria}"

    m_tipo = _TIPO.search(query)
    m_status = _STATUS.search(query)
    etapa = (m_tipo.group(1).split("_")[-1] if m_tipo else "?")
    if m_status:
        etapa = f"{etapa} {m_status.group(1)}"
    return canal, etapa


def localizar() -> dict[str, Path]:
    """Captura mais recente de cada emissor.

    So considera arquivo com codigo de emissor no nome: captura geral
    misturaria os emissores, que e o que se quer evitar aqui.
    """
    if not PASTA_CAPTURAS.exists():
        raise ErroCaptura(
            f"a pasta {PASTA_CAPTURAS.name}/ nao existe."
            " Rode antes: 3_capturar_emissores.bat"
        )

    arquivos = sorted(p for p in PASTA_CAPTURAS.iterdir() if p.is_file())
    if not arquivos:
        raise ErroCaptura(
            f"a pasta {PASTA_CAPTURAS.name}/ esta vazia."
            " Rode antes: 3_capturar_emissores.bat"
        )

    encontrados: dict[str, Path] = {}
    for arquivo in sorted(PASTA_CAPTURAS.glob("*.json")):
        m = _CODIGO_ARQUIVO.search(arquivo.name)
        if m:
            encontrados[m.group(1)] = arquivo  # ordenado: fica o mais recente

    if encontrados:
        return encontrados

    # Diagnostico preciso: 'rode a captura' e resposta errada quando a
    # captura rodou e o que faltou foi o sink json.
    jsons = [p for p in arquivos if p.suffix.lower() == ".json"]
    if not jsons:
        tipos = ", ".join(sorted({p.suffix or "?" for p in arquivos}))
        raise ErroCaptura(
            f"ha {len(arquivos)} arquivo(s) em {PASTA_CAPTURAS.name}/ ({tipos}),"
            " mas nenhum .json.\n"
            "A precificacao precisa do sink json: so ele carrega a query de\n"
            "cada valor, que e o que permite saber canal e etapa.\n"
            "Ligue em config/settings.yaml:  sinks: { json: true }\n"
            "e rode a captura de novo."
        )
    raise ErroCaptura(
        f"ha {len(jsons)} json em {PASTA_CAPTURAS.name}/, mas nenhum com codigo"
        " de emissor no nome.\nRode: 3_capturar_emissores.bat"
    )


def ler(codigo: str, arquivo: Path) -> UsoEmissor:
    """Extrai da captura o que a precificacao consome."""
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErroCaptura(f"nao foi possivel ler {arquivo.name}: {exc}") from None

    medicoes = dados.get("medicoes")
    if not isinstance(medicoes, list):
        raise ErroCaptura(f"{arquivo.name} nao tem a lista 'medicoes'")

    uso = UsoEmissor(codigo=codigo, arquivo=arquivo)
    uso.dashboard = str((dados.get("dashboard") or {}).get("titulo") or "")
    janela = dados.get("janela") or {}
    uso.janela = f"{str(janela.get('from'))[:10]} a {str(janela.get('to'))[:10]}"

    # --- Volume de eventos: topo do funil, sem risco de dupla contagem ----
    for alvo in ("total requisitadas", "1. requisitadas"):
        for m in medicoes:
            nome = (m.get("nome_valor") or "").strip().lower()
            valor = m.get("valor")
            if nome == alvo and isinstance(valor, (int, float)):
                uso.eventos = Decimal(str(valor))
                uso.origem_eventos = m["nome_valor"]
                break
        if uso.origem_eventos:
            break

    if not uso.origem_eventos:
        log.warning(
            "emissor %s: campo de requisicoes totais nao encontrado -"
            " o SIC sera calculado com zero evento",
            codigo,
        )

    # --- Volume enviado por canal (etapa faturavel) -----------------------
    enviados: dict[str, Decimal] = defaultdict(Decimal)
    for m in medicoes:
        canal, etapa = _classificar(m.get("query") or "")
        if not canal or not etapa.endswith(STATUS_FATURAVEL):
            continue
        valor = m.get("valor")
        if isinstance(valor, (int, float)) and valor > 0:
            enviados[canal] += Decimal(str(valor))
    uso.enviado_por_canal = dict(enviados)

    # --- Canais com uso, do widget de quantidade por canais ---------------
    somas: dict[str, Decimal] = defaultdict(Decimal)
    rotulos: dict[str, str] = {}
    for m in medicoes:
        if not _WIDGET_CANAIS.search(m.get("widget_titulo") or ""):
            continue
        canal, _ = _classificar(m.get("query") or "")
        if not canal:
            # Quando a quebra e por group_by o sufixo vem como facet cru
            # ('@log.messageChannel:WhatsApp'); so o valor apos ':' serve.
            partes = (m.get("nome_valor") or "").rsplit(" - ", 1)
            canal = partes[1].rsplit(":", 1)[-1] if len(partes) == 2 else ""
        canal = canal.split("/")[0].strip()
        if not canal or canal.startswith("("):
            continue
        rotulos.setdefault(canal.lower(), canal)
        valor = m.get("valor")
        if isinstance(valor, (int, float)):
            somas[canal.lower()] += Decimal(str(valor))

    uso.canais_com_uso = {
        rotulos[k]: v for k, v in somas.items() if v > 0
    }

    log.info(
        "emissor %s: %s eventos, %d canal(is) enviando, %d canal(is) com uso",
        codigo,
        f"{uso.eventos:,.0f}",
        len(uso.enviado_por_canal),
        len(uso.canais_com_uso),
    )
    return uso


def carregar_todos() -> list[UsoEmissor]:
    """Todas as capturas por emissor, prontas para precificar."""
    return [ler(codigo, arquivo) for codigo, arquivo in sorted(localizar().items())]
