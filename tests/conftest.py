from __future__ import annotations

import json
from pathlib import Path

import pytest

from ddcapture.config import carregar
from ddcapture.dashboard import achatar_widgets, valores_template_vars

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def dashboard() -> dict:
    with (FIXTURES / "dashboard_sample.json").open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def config():
    # exigir_credenciais=False: os testes nao tocam a rede.
    cfg = carregar(RAIZ / "config", exigir_credenciais=False)
    cfg.dashboard_id = "abc-def-ghi"
    return cfg


@pytest.fixture
def widgets(dashboard):
    return achatar_widgets(dashboard)


@pytest.fixture
def por_titulo(widgets):
    return {w.titulo: w for w in widgets}


@pytest.fixture
def valores_vars(dashboard):
    return valores_template_vars(dashboard)
