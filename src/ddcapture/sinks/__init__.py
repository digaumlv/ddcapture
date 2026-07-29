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
    """Nome base dos arquivos: dashboard + instante da captura."""
    from datetime import datetime, timezone

    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in resultado.dashboard_id)
    return f"{slug or 'dashboard'}_{carimbo}"
