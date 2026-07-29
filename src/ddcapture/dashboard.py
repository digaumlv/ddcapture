"""Fase 1: buscar a definicao do dashboard e achatar a arvore de widgets.

A API de dashboard devolve apenas a estrutura - titulos, layout e as queries.
Nenhum valor. Achatar aqui e o que permite tratar cada widget de forma uniforme
na fase 2, sem perder a hierarquia de grupos (que vira a categoria camada 1).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from .client import DatadogClient
from .models import Widget

# $var, ${var} ou $var.value dentro de uma query. As duas alternativas sao
# necessarias: um '\}?' opcional engoliria a chave que fecha o escopo em
# '{env:$env}'.
_TEMPLATE_VAR = re.compile(r"\$(?:\{([a-zA-Z0-9_.-]+)\}|([a-zA-Z0-9_.-]+))")


def buscar_dashboard(client: DatadogClient, dashboard_id: str) -> dict[str, Any]:
    """GET /api/v1/dashboard/{id} - a definicao crua."""
    return client.get(f"/api/v1/dashboard/{dashboard_id}")


def carregar_dashboard_de_arquivo(caminho: Path) -> dict[str, Any]:
    """Le uma definicao ja salva em disco. Usado nos testes e no --dry-run offline."""
    with Path(caminho).open(encoding="utf-8") as fh:
        return json.load(fh)


def listar_dashboards(client: DatadogClient) -> list[dict[str, Any]]:
    """GET /api/v1/dashboard - util para descobrir o id pelo titulo."""
    return list(client.get("/api/v1/dashboard").get("dashboards") or [])


def achatar_widgets(dashboard: dict[str, Any]) -> list[Widget]:
    """Percorre a arvore e devolve todos os widgets em lista plana.

    Widgets do tipo 'group' guardam os filhos em definition.widgets. O grupo em
    si nao produz valor, mas seu titulo acompanha cada filho.
    """
    return list(_percorrer(dashboard.get("widgets") or [], caminho=[]))


def _percorrer(widgets: list[dict[str, Any]], caminho: list[str]) -> Iterator[Widget]:
    for bruto in widgets:
        definition = bruto.get("definition") or {}
        tipo = str(definition.get("type") or "desconhecido")
        titulo = str(definition.get("title") or "").strip()
        widget_id = str(bruto.get("id") or "")

        if tipo == "group":
            # O titulo do grupo entra no caminho dos filhos; o grupo nao vira
            # Widget porque nao carrega valor proprio.
            filho_caminho = caminho + [titulo] if titulo else list(caminho)
            yield from _percorrer(definition.get("widgets") or [], filho_caminho)
            continue

        yield Widget(
            widget_id=widget_id,
            tipo=tipo,
            titulo=titulo,
            grupo_pai=caminho[-1] if caminho else None,
            caminho_grupos=list(caminho),
            definition=definition,
        )


def prefixos_template_vars(dashboard: dict[str, Any]) -> dict[str, str]:
    """Mapa nome -> prefixo (facet) declarado na template variable.

    O dashboard guarda `$TipoCanal`, mas a variavel declara prefix
    `@log.messageChannel`. Sem o prefixo, `--var TipoCanal=SMS` viraria uma
    busca por texto livre em vez de um filtro de facet.
    """
    prefixos: dict[str, str] = {}
    for var in dashboard.get("template_variables") or []:
        nome = str(var.get("name") or "").strip()
        prefixo = str(var.get("prefix") or "").strip()
        if nome and prefixo:
            prefixos[nome] = prefixo
    return prefixos


def valores_template_vars(
    dashboard: dict[str, Any],
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Monta o mapa nome -> valor das template variables do dashboard.

    Usa o `default` de cada variavel; `--var chave=valor` sobrescreve. Um default
    ausente ou '*' vira '*', que e o coringa aceito nas queries.
    """
    valores: dict[str, str] = {}
    for var in dashboard.get("template_variables") or []:
        nome = str(var.get("name") or "").strip()
        if not nome:
            continue
        padrao = var.get("default")
        if isinstance(padrao, list):
            padrao = padrao[0] if padrao else "*"
        valores[nome] = str(padrao) if padrao not in (None, "") else "*"

    valores.update(overrides or {})
    return valores


def substituir_template_vars(
    query: str,
    valores: dict[str, str],
    prefixos: dict[str, str] | None = None,
) -> str:
    """Troca $var pelo valor correspondente, respeitando a posicao na query.

    Duas posicoes, dois comportamentos:

      valor de tag  'env:$env'  -> 'env:prod'   ('*' e mantido: env:* e valido)
      token solto   '... $BIN'  -> '@cardBin:1234', e SOME quando o valor e '*'

    Sem essa distincao, um dashboard cheio de variaveis opcionais (o padrao no
    Datadog) produz uma busca terminada em '* * * * * * *', e um --var passado
    pelo usuario viraria texto livre em vez de filtro de facet.
    """
    if "$" not in query:
        return query

    prefixos = prefixos or {}

    def _trocar(m: re.Match[str]) -> str:
        nome = m.group(1) or m.group(2)
        # $service.value e a forma longa de $service.
        base = nome if nome in valores else nome.split(".")[0]
        valor = valores.get(base, "*")

        # Precedido por ':' significa que ja estamos do lado do valor da tag.
        anterior = query[m.start() - 1] if m.start() > 0 else ""
        if anterior == ":":
            return valor

        if valor == "*":
            return ""
        prefixo = prefixos.get(base, "")
        return f"{prefixo}:{valor}" if prefixo else valor

    # Remover tokens deixa espacos duplos para tras.
    return re.sub(r"\s{2,}", " ", _TEMPLATE_VAR.sub(_trocar, query)).strip()
