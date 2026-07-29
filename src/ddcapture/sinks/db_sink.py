"""Saida SQLite: cada execucao vira um snapshot, permitindo comparar no tempo.

Duas tabelas: `execucoes` (uma linha por run) e `medicoes` (FK para a execucao).
O arquivo e reaproveitado entre runs - nunca sobrescrito.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..config import Config
from ..runner import Resultado

_SCHEMA = """
CREATE TABLE IF NOT EXISTS execucoes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    dashboard_id       TEXT NOT NULL,
    dashboard_titulo   TEXT,
    janela_inicio_s    INTEGER NOT NULL,
    janela_fim_s       INTEGER NOT NULL,
    executado_em       TEXT NOT NULL,
    widgets_total      INTEGER,
    queries_total      INTEGER,
    valores_total      INTEGER,
    falhas_total       INTEGER
);

CREATE TABLE IF NOT EXISTS medicoes (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    execucao_id        INTEGER NOT NULL REFERENCES execucoes(id) ON DELETE CASCADE,
    categoria          TEXT NOT NULL,
    categoria_origem   TEXT NOT NULL,
    grupo_pai          TEXT,
    caminho_grupos     TEXT,
    widget_id          TEXT,
    widget_titulo      TEXT,
    widget_tipo        TEXT,
    nome_valor         TEXT NOT NULL,
    valor              REAL,
    unidade            TEXT,
    timestamp          INTEGER,
    data_source        TEXT,
    agregador          TEXT,
    query              TEXT,
    tags               TEXT,
    erro               TEXT
);

CREATE INDEX IF NOT EXISTS idx_medicoes_execucao  ON medicoes(execucao_id);
CREATE INDEX IF NOT EXISTS idx_medicoes_categoria ON medicoes(categoria);
CREATE INDEX IF NOT EXISTS idx_medicoes_nome      ON medicoes(nome_valor);
"""

# Serie historica de um valor: o mesmo nome ao longo das execucoes.
_VIEW_HISTORICO = """
CREATE VIEW IF NOT EXISTS historico AS
SELECT
    e.dashboard_id,
    e.executado_em,
    m.categoria,
    m.widget_titulo,
    m.nome_valor,
    m.valor,
    m.unidade
FROM medicoes m
JOIN execucoes e ON e.id = m.execucao_id
ORDER BY m.nome_valor, e.executado_em;
"""


def gravar(resultado: Resultado, config: Config) -> Path:
    caminho = config.saida_dir / config.sqlite_arquivo
    conexao = sqlite3.connect(caminho)
    try:
        conexao.executescript(_SCHEMA)
        conexao.executescript(_VIEW_HISTORICO)

        cursor = conexao.execute(
            """
            INSERT INTO execucoes (
                dashboard_id, dashboard_titulo, janela_inicio_s, janela_fim_s,
                executado_em, widgets_total, queries_total, valores_total, falhas_total
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                resultado.dashboard_id,
                resultado.dashboard_titulo,
                resultado.inicio_s,
                resultado.fim_s,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                len(resultado.widgets),
                len(resultado.specs),
                len(resultado.capturados),
                len(resultado.falhas),
            ),
        )
        execucao_id = cursor.lastrowid

        conexao.executemany(
            """
            INSERT INTO medicoes (
                execucao_id, categoria, categoria_origem, grupo_pai, caminho_grupos,
                widget_id, widget_titulo, widget_tipo, nome_valor, valor, unidade,
                timestamp, data_source, agregador, query, tags, erro
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    execucao_id,
                    m.categoria,
                    m.categoria_origem,
                    m.grupo_pai,
                    " > ".join(m.caminho_grupos),
                    m.widget_id,
                    m.widget_titulo,
                    m.widget_tipo,
                    m.nome_valor,
                    m.valor,
                    m.unidade,
                    m.timestamp,
                    m.data_source,
                    m.agregador,
                    m.query,
                    json.dumps(m.tags, ensure_ascii=False),
                    m.erro,
                )
                for m in resultado.medicoes
            ],
        )
        conexao.commit()
    finally:
        conexao.close()

    return caminho
