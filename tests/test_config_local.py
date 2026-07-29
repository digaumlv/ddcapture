"""settings.local.yaml: override fora do versionamento.

E onde vai o dashboard_id da instalacao, para nao virar commit num
repositorio publico.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from ddcapture.config import carregar

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir(tmp_path) -> Path:
    """Copia os YAMLs versionados para um diretorio descartavel."""
    destino = tmp_path / "config"
    destino.mkdir()
    for nome in ("settings.yaml", "categorias.yaml"):
        shutil.copy(RAIZ / "config" / nome, destino / nome)
    return destino


def _escrever_local(config_dir: Path, dados: dict) -> None:
    (config_dir / "settings.local.yaml").write_text(
        yaml.safe_dump(dados, allow_unicode=True), encoding="utf-8"
    )


def test_sem_arquivo_local_usa_so_o_settings(config_dir):
    """O arquivo e opcional - sua ausencia nao pode quebrar nada."""
    cfg = carregar(config_dir, exigir_credenciais=False)
    assert cfg.dashboard_id == ""


def test_local_define_o_dashboard(config_dir):
    _escrever_local(config_dir, {"dashboard_id": "abc-def-ghi"})

    cfg = carregar(config_dir, exigir_credenciais=False)
    assert cfg.dashboard_id == "abc-def-ghi"


def test_local_vence_o_settings(config_dir):
    _escrever_local(config_dir, {"agregador_padrao": "sum"})

    cfg = carregar(config_dir, exigir_credenciais=False)
    assert cfg.agregador_padrao == "sum"


def test_merge_e_profundo_em_janela(config_dir):
    """Declarar so `from` nao pode apagar o `to` do settings.yaml."""
    base = yaml.safe_load((config_dir / "settings.yaml").read_text(encoding="utf-8"))
    to_original = base["janela"]["to"]

    _escrever_local(config_dir, {"janela": {"from": "-7d"}})

    cfg = carregar(config_dir, exigir_credenciais=False)
    assert cfg.janela_from == "-7d"
    assert cfg.janela_to == to_original


def test_merge_e_profundo_em_sinks(config_dir):
    _escrever_local(config_dir, {"sinks": {"csv": True}})

    cfg = carregar(config_dir, exigir_credenciais=False)
    assert cfg.sinks["csv"] is True
    # xlsx continua vindo do settings.yaml.
    assert cfg.sinks["xlsx"] is True


def test_local_vazio_nao_quebra(config_dir):
    (config_dir / "settings.local.yaml").write_text("", encoding="utf-8")

    cfg = carregar(config_dir, exigir_credenciais=False)
    assert cfg.dashboard_id == ""


def test_exemplo_do_local_e_yaml_valido():
    """O .example e copiado pelo usuario - precisa carregar sem editar."""
    caminho = RAIZ / "config" / "settings.local.yaml.example"
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))

    assert "dashboard_id" in dados


def test_settings_versionado_nao_traz_dashboard_id():
    """O ID real mora no arquivo local; o versionado vai vazio."""
    dados = yaml.safe_load(
        (RAIZ / "config" / "settings.yaml").read_text(encoding="utf-8")
    )
    assert dados.get("dashboard_id") == ""


# --- Execucao sem argumentos --------------------------------------------


def _config_falsa(config_dir, dashboard_id: str):
    from ddcapture.config import Credenciais, carregar as carregar_real

    def _fake(*args, **kwargs):
        cfg = carregar_real(config_dir, exigir_credenciais=False)
        cfg.credenciais = Credenciais(api_key="x", app_key="y", site="datadoghq.com")
        cfg.dashboard_id = dashboard_id
        return cfg

    return _fake


def test_sem_argumentos_e_sem_dashboard_mostra_ajuda(config_dir, monkeypatch, capsys):
    """Quem deu duplo clique sem configurar merece instrucao, nao erro."""
    from ddcapture import cli

    monkeypatch.setattr(cli, "carregar", _config_falsa(config_dir, ""))
    monkeypatch.setattr(cli, "DatadogClient", lambda *a, **k: object())

    assert cli.main([]) == 0

    saida = capsys.readouterr().out
    assert "settings.local.yaml" in saida
    assert "--buscar" in saida


def test_com_argumentos_e_sem_dashboard_da_erro(config_dir, monkeypatch, capsys):
    """Quem digitou um comando quer executar algo: falhar e o certo."""
    from ddcapture import cli

    monkeypatch.setattr(cli, "carregar", _config_falsa(config_dir, ""))
    monkeypatch.setattr(cli, "DatadogClient", lambda *a, **k: object())

    assert cli.main(["--from", "-1h"]) == 2
    assert "settings.local.yaml" in capsys.readouterr().err
