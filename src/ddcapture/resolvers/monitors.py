"""Resolver de widgets de monitor (manage_status, alert_graph, monitor_summary).

Esses widgets nao exibem uma metrica e sim a contagem de monitores por estado.
O valor capturado e essa contagem - um numero por estado, nomeado pelo estado.
"""

from __future__ import annotations

from ..client import DatadogClient, ErroApi
from ..models import QuerySpec
from . import ValorBruto

# Ordem de severidade, para a saida sair sempre na mesma sequencia.
_ESTADOS = ("Alert", "Warn", "No Data", "OK", "Skipped", "Ignored", "Unknown")


def resolver(
    client: DatadogClient,
    spec: QuerySpec,
    inicio_s: int,
    fim_s: int,
) -> list[ValorBruto]:
    busca = str(spec.extra.get("query") or "").strip()

    params: dict[str, str] = {}
    if busca:
        # A busca do widget usa a mesma sintaxe do endpoint de monitores.
        params["monitor_tags"] = busca if ":" in busca else ""
        params["name"] = "" if ":" in busca else busca
        params = {k: v for k, v in params.items() if v}

    try:
        resposta = client.get("/api/v1/monitor", params=params or None)
    except ErroApi as exc:
        return [ValorBruto(nome=spec.widget.titulo_efetivo, valor=None, erro=str(exc))]

    # O endpoint devolve uma lista crua; o DatadogClient a embrulha em {"data": [...]}.
    if isinstance(resposta, list):
        monitores = resposta
    elif isinstance(resposta.get("data"), list):
        monitores = resposta["data"]
    else:
        monitores = []

    contagem: dict[str, int] = {}
    for monitor in monitores:
        if not isinstance(monitor, dict):
            continue
        estado = str(monitor.get("overall_state") or "Unknown")
        contagem[estado] = contagem.get(estado, 0) + 1

    if not contagem:
        return [
            ValorBruto(
                nome=spec.widget.titulo_efetivo,
                valor=0.0,
                unidade="monitores",
                tags={"estado": "nenhum"},
            )
        ]

    base = spec.widget.titulo_efetivo
    ordenados = sorted(
        contagem.items(),
        key=lambda kv: (_ESTADOS.index(kv[0]) if kv[0] in _ESTADOS else len(_ESTADOS), kv[0]),
    )

    valores = [
        ValorBruto(
            nome=f"{base} - {estado}",
            valor=float(qtd),
            unidade="monitores",
            tags={"estado": estado},
        )
        for estado, qtd in ordenados
    ]
    valores.append(
        ValorBruto(
            nome=f"{base} - total",
            valor=float(sum(contagem.values())),
            unidade="monitores",
            tags={"estado": "total"},
        )
    )
    return valores
