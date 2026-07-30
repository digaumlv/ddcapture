"""Fase 4: gravacao dos resultados."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..runner import Resultado


def gravar_todos(resultado: Resultado, config: Config) -> list[Path]:
    """Executa os sinks habilitados no settings.yaml. Devolve os arquivos escritos."""
    from . import csv_sink, db_sink, excel_sink, excel_widget_sink, json_sink

    config.saida_dir.mkdir(parents=True, exist_ok=True)
    escritos: list[Path] = []

    if config.sinks.get("json"):
        escritos.append(json_sink.gravar(resultado, config))
    if config.sinks.get("csv"):
        escritos.append(csv_sink.gravar(resultado, config))
    if config.sinks.get("xlsx"):
        escritos.append(excel_sink.gravar(resultado, config))
    if config.sinks.get("xlsx_por_widget"):
        escritos.append(excel_widget_sink.gravar(resultado, config))
    if config.sinks.get("sqlite"):
        escritos.append(db_sink.gravar(resultado, config))

    return escritos


def prefixo_arquivo(resultado: Resultado) -> str:
    """Nome base dos arquivos: dashboard + filtros + instante da captura.

    Os filtros (--var) entram no nome porque sao o que distingue uma captura
    da outra. Sem eles, rodar por emissor gera arquivos separados apenas pelo
    timestamp - impossivel saber qual e de quem depois.
    """
    from datetime import datetime, timezone

    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    partes = [_slug(resultado.dashboard_id) or "dashboard"]

    if resultado.rotulo:
        # O rotulo existe porque o valor do filtro nem sempre serve de nome:
        # '(1234 OR 234)' viraria '-1234-OR-234-'.
        partes.append(_slug(resultado.rotulo))
    else:
        for chave, valor in sorted(resultado.filtros.items()):
            partes.append(f"{_slug(chave)}-{_slug(valor)}")

    partes.append(carimbo)
    return "_".join(partes)


def _slug(texto: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in str(texto))
