"""Importa as tabelas de preco (CSV pt-BR) para um banco SQLite.

    python importar_precos.py

Le tabela_precos_sic.csv e tabela_piso_canais.csv da pasta do projeto e grava
precos.sqlite. Idempotente: recria as tabelas a cada execucao.

O ponto do script e a conversao numerica. Nos CSVs os valores estao no formato
brasileiro ('1.000.000,00', '0,03393'), que o SQLite guardaria como TEXTO -
qualquer SUM ou multiplicacao daria errado silenciosamente. Aqui eles entram
como INTEGER e REAL.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "precos.sqlite"

_SCHEMA = """
DROP TABLE IF EXISTS faixas_preco;
CREATE TABLE faixas_preco (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    faixa_inicial               INTEGER,          -- NULL na primeira faixa (sem piso)
    faixa_final                 INTEGER NOT NULL,
    tipo_tarifa                 TEXT    NOT NULL, -- Fixa | Variavel
    tarifa_eventos_financeiros  REAL,
    tarifa_eventos_nao_financeiros REAL
);

DROP TABLE IF EXISTS piso_canais;
CREATE TABLE piso_canais (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canal           TEXT NOT NULL,
    tipo_tarifa     TEXT NOT NULL,                -- fixa | variavel
    valor_inicial   REAL,                         -- NULL: o original traz '-'
    valor_final     REAL,
    tarifa_inicial  REAL,
    tarifa_final    REAL
);

DROP VIEW IF EXISTS faixas_variaveis;
CREATE VIEW faixas_variaveis AS
SELECT faixa_inicial, faixa_final,
       tarifa_eventos_financeiros AS tarifa_financeiro,
       tarifa_eventos_nao_financeiros AS tarifa_nao_financeiro
FROM faixas_preco
WHERE tipo_tarifa LIKE 'Vari%'
ORDER BY faixa_final;

DROP VIEW IF EXISTS desconto_por_canal;
CREATE VIEW desconto_por_canal AS
SELECT canal, tipo_tarifa, tarifa_inicial, tarifa_final,
       ROUND((tarifa_inicial - tarifa_final) * 100.0 / tarifa_inicial, 2) AS desconto_pct
FROM piso_canais
WHERE tarifa_inicial > 0
ORDER BY desconto_pct DESC;
"""


def numero(texto: str | None) -> float | None:
    """Converte numero em formato brasileiro para float.

    '1.000.000,00' -> 1000000.0     ponto e separador de milhar
    '0,03393'      -> 0.03393       virgula e separador decimal
    '' ou '-'      -> None          celula vazia no original
    """
    if texto is None:
        return None
    limpo = texto.strip().replace("R$", "").strip()
    if limpo in ("", "-"):
        return None
    # Ordem importa: tirar os pontos primeiro, senao '1.000,00' viraria 1.0.
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        print(f"  aviso: valor nao numerico ignorado: {texto!r}", file=sys.stderr)
        return None


def inteiro(texto: str | None) -> int | None:
    valor = numero(texto)
    return None if valor is None else int(valor)


def _ler_csv(caminho: Path) -> list[dict[str, str]]:
    if not caminho.exists():
        raise SystemExit(f"Arquivo nao encontrado: {caminho.name}")
    # utf-8-sig descarta o BOM que os CSVs carregam para o Excel pt-BR.
    with caminho.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def importar_faixas(conexao: sqlite3.Connection) -> int:
    linhas = _ler_csv(RAIZ / "tabela_precos_sic.csv")
    dados = [
        (
            inteiro(l.get("Faixa Inicial")),
            inteiro(l.get("Faixa Final")),
            (l.get("Tipo de Tarifa") or "").strip(),
            numero(l.get("Tarifa Eventos Financeiros")),
            numero(l.get("Tarifa Eventos Nao Financeiros")),
        )
        for l in linhas
    ]
    conexao.executemany(
        """INSERT INTO faixas_preco
           (faixa_inicial, faixa_final, tipo_tarifa,
            tarifa_eventos_financeiros, tarifa_eventos_nao_financeiros)
           VALUES (?, ?, ?, ?, ?)""",
        dados,
    )
    return len(dados)


def importar_piso(conexao: sqlite3.Connection) -> int:
    linhas = _ler_csv(RAIZ / "tabela_piso_canais.csv")
    dados = [
        (
            (l.get("Canal") or "").strip(),
            (l.get("Tipo tarifa") or "").strip(),
            numero(l.get("Valor inicial")),
            numero(l.get("Valor final")),
            numero(l.get("Tarifa Inicial")),
            numero(l.get("Tarifa Final")),
        )
        for l in linhas
    ]
    conexao.executemany(
        """INSERT INTO piso_canais
           (canal, tipo_tarifa, valor_inicial, valor_final,
            tarifa_inicial, tarifa_final)
           VALUES (?, ?, ?, ?, ?, ?)""",
        dados,
    )
    return len(dados)


def main() -> int:
    conexao = sqlite3.connect(BANCO)
    try:
        conexao.executescript(_SCHEMA)
        n_faixas = importar_faixas(conexao)
        n_piso = importar_piso(conexao)
        conexao.commit()
    finally:
        conexao.close()

    print(f"{BANCO.name}")
    print(f"  faixas_preco : {n_faixas} linha(s)")
    print(f"  piso_canais  : {n_piso} linha(s)")
    print("  views        : faixas_variaveis, desconto_por_canal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
