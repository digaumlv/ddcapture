"""Resolver de widgets de SLO: GET /api/v1/slo/{id}/history.

O valor exibido no widget e o SLI do periodo, entao capturamos o sli global e,
quando presentes, os SLIs por janela de tempo (7d, 30d, 90d).
"""

from __future__ import annotations

from ..client import DatadogClient, ErroApi
from ..models import QuerySpec
from . import ValorBruto


def resolver(
    client: DatadogClient,
    spec: QuerySpec,
    inicio_s: int,
    fim_s: int,
) -> list[ValorBruto]:
    slo_id = spec.extra.get("slo_id")
    if not slo_id:
        return [ValorBruto(nome=spec.widget.titulo_efetivo, valor=None, erro="widget de SLO sem slo_id")]

    try:
        resposta = client.get(
            f"/api/v1/slo/{slo_id}/history",
            params={"from_ts": inicio_s, "to_ts": fim_s},
        )
    except ErroApi as exc:
        return [ValorBruto(nome=spec.widget.titulo_efetivo, valor=None, erro=str(exc))]

    dados = resposta.get("data") or {}
    nome_slo = str((dados.get("slo") or {}).get("name") or spec.widget.titulo_efetivo)

    valores: list[ValorBruto] = []

    overall = dados.get("overall") or {}
    sli = overall.get("sli_value")
    if isinstance(sli, (int, float)):
        valores.append(
            ValorBruto(
                nome=f"{nome_slo} - SLI",
                valor=float(sli),
                unidade="%",
                tags={"slo_id": str(slo_id)},
            )
        )

    alvo = overall.get("target") or (dados.get("thresholds") or {}).get("target")
    if isinstance(alvo, (int, float)):
        valores.append(
            ValorBruto(
                nome=f"{nome_slo} - alvo",
                valor=float(alvo),
                unidade="%",
                tags={"slo_id": str(slo_id)},
            )
        )

    restante = overall.get("error_budget_remaining")
    if isinstance(restante, (int, float)):
        valores.append(
            ValorBruto(
                nome=f"{nome_slo} - error budget restante",
                valor=float(restante),
                unidade="%",
                tags={"slo_id": str(slo_id)},
            )
        )

    # SLIs por janela, quando o SLO define varias.
    janelas = dados.get("time_windows")
    if isinstance(janelas, dict):
        for janela, bloco in janelas.items():
            if not isinstance(bloco, dict):
                continue
            sli_janela = bloco.get("sli_value")
            if isinstance(sli_janela, (int, float)):
                valores.append(
                    ValorBruto(
                        nome=f"{nome_slo} - SLI {janela}",
                        valor=float(sli_janela),
                        unidade="%",
                        tags={"slo_id": str(slo_id), "janela": str(janela)},
                    )
                )

    if not valores:
        valores.append(ValorBruto(nome=nome_slo, valor=0.0, sem_dados=True))
    return valores
