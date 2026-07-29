"""Ponto de entrada do coletor de dashboards do Datadog.

Rode sempre por aqui: este arquivo poe `src/` no path, entao nao e preciso
mexer no PYTHONPATH nem instalar o pacote.

    .\\.venv\\Scripts\\python.exe main.py --validar
    .\\.venv\\Scripts\\python.exe main.py --buscar "parte do titulo"
    .\\.venv\\Scripts\\python.exe main.py --dashboard-id abc-def-ghi --dry-run
    .\\.venv\\Scripts\\python.exe main.py --dashboard-id abc-def-ghi --from -1h

SOMENTE LEITURA: o cliente HTTP so aceita GET e os POST dos endpoints de
consulta (que apenas leem). Qualquer outra chamada e barrada antes de sair,
em client._garantir_leitura. Nada e criado, alterado ou apagado no Datadog.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ddcapture.cli import main  # noqa: E402  (precisa vir depois do sys.path)

if __name__ == "__main__":
    raise SystemExit(main())
