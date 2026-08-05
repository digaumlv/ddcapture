"""Carga das tabelas de preco a partir dos CSV.

Os quatro CSV da raiz sao a fonte de verdade dos valores de negocio. Aqui
eles viram tabelas; nenhum numero e escrito no codigo.

    tabela_precos_sic.csv        faixas do SIC (fixa + variaveis)
    tabela_piso_canais.csv       tarifas do broker de comunicacao, por canal
    tabela_valores_fixos.csv     valores fixos e a condicao de cobranca
    tabela_servicos_emissor.csv  o que cada emissor contratou

A conversao numerica e o ponto critico: os CSV estao em formato brasileiro
('1.000.000,00'), e gravar como texto faria SUM concatenar e comparacao
ordenar alfabeticamente, tudo em silencio.
"""

from __future__ import annotations

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .configuracao import RAIZ

log = logging.getLogger(__name__)

ARQUIVOS = {
    "faixas_sic": RAIZ / "tabela_precos_sic.csv",
    "tarifas_canal": RAIZ / "tabela_piso_canais.csv",
    "valores_fixos": RAIZ / "tabela_valores_fixos.csv",
    "servicos_emissor": RAIZ / "tabela_servicos_emissor.csv",
    "apelidos_canal": RAIZ / "tabela_canais_apelido.csv",
}

_SCHEMA = """
DROP TABLE IF EXISTS faixas_sic;
CREATE TABLE faixas_sic (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    faixa_inicial  INTEGER,          -- NULL na primeira faixa: nao tem piso
    faixa_final    INTEGER NOT NULL,
    tipo_tarifa    TEXT    NOT NULL, -- fixa | variavel
    tarifa_financeiro     NUMERIC,
    tarifa_nao_financeiro NUMERIC
);

DROP TABLE IF EXISTS tarifas_canal;
CREATE TABLE tarifas_canal (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    canal          TEXT    NOT NULL,
    tipo_tarifa    TEXT    NOT NULL,
    limite         NUMERIC,          -- volume onde a tarifa troca
    tarifa_inicial NUMERIC,
    tarifa_final   NUMERIC
);

DROP TABLE IF EXISTS valores_fixos;
CREATE TABLE valores_fixos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    origem     TEXT    NOT NULL,
    item       TEXT    NOT NULL,
    canal      TEXT,
    valor      NUMERIC NOT NULL,
    condicao   TEXT    NOT NULL,     -- sempre | canal_com_uso | acima_da_franquia
    observacao TEXT
);

DROP TABLE IF EXISTS apelidos_canal;
-- Liga o nome do canal como sai da captura ao canal da tabela de tarifas.
-- `canal_tarifa` vazio marca canal a NAO precificar - e como se declara,
-- por dado, que aquela serie sobrepoe outra e causaria dupla contagem.
CREATE TABLE apelidos_canal (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canal_captura TEXT NOT NULL UNIQUE,
    canal_tarifa  TEXT,
    observacao    TEXT
);

DROP TABLE IF EXISTS servicos_fixos;
CREATE TABLE servicos_fixos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo     TEXT    NOT NULL,     -- codigo do emissor, como no @org
    emissor    TEXT,
    servico    TEXT    NOT NULL,
    valor_fixo NUMERIC,              -- NULL se o servico nao tem valor fixo
    ativo      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (codigo, servico)
);
"""


class ErroCarga(Exception):
    """CSV ausente, malformado ou inconsistente."""


def numero(texto: str | None) -> Decimal | None:
    """Converte numero em formato brasileiro para Decimal.

        '1.000.000,00' -> 1000000.00
        '0,03393'      -> 0.03393
        '' ou '-'      -> None

    A ordem importa: tirar os pontos de milhar ANTES de trocar a virgula
    decimal. Invertido, '1.000,00' viraria 1.0.
    """
    if texto is None:
        return None
    limpo = str(texto).strip().replace("R$", "").strip()
    if limpo in ("", "-"):
        return None
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        raise ErroCarga(f"valor nao numerico no CSV: {texto!r}") from None


def _inteiro(texto: str | None) -> int | None:
    valor = numero(texto)
    return None if valor is None else int(valor)


def _ler(caminho: Path) -> list[dict[str, str]]:
    if not caminho.exists():
        raise ErroCarga(f"arquivo nao encontrado: {caminho.name}")
    # utf-8-sig descarta o BOM que os CSV carregam para abrir bem no Excel.
    with caminho.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def executar(conexao) -> dict[str, int]:
    """Recria as tabelas a partir dos CSV. Idempotente."""
    cursor = conexao.cursor()
    cursor.executescript(_SCHEMA) if hasattr(cursor, "executescript") else None
    if not hasattr(cursor, "executescript"):
        for comando in _SCHEMA.split(";"):
            if comando.strip():
                cursor.execute(comando)

    contagens: dict[str, int] = {}

    # --- Faixas do SIC ----------------------------------------------------
    linhas = _ler(ARQUIVOS["faixas_sic"])
    dados = [
        (
            _inteiro(l.get("Faixa Inicial")),
            _inteiro(l.get("Faixa Final")),
            (l.get("Tipo de Tarifa") or "").strip().lower(),
            str(numero(l.get("Tarifa Eventos Financeiros")) or ""),
            str(numero(l.get("Tarifa Eventos Nao Financeiros")) or ""),
        )
        for l in linhas
    ]
    cursor.executemany(
        "INSERT INTO faixas_sic (faixa_inicial, faixa_final, tipo_tarifa,"
        " tarifa_financeiro, tarifa_nao_financeiro) VALUES (?, ?, ?, ?, ?)",
        dados,
    )
    contagens["faixas_sic"] = len(dados)

    # --- Tarifas do broker de comunicacao ---------------------------------
    linhas = _ler(ARQUIVOS["tarifas_canal"])
    dados = [
        (
            (l.get("Canal") or "").strip(),
            (l.get("Tipo tarifa") or "").strip().lower(),
            str(numero(l.get("Valor final")) or ""),
            str(numero(l.get("Tarifa Inicial")) or ""),
            str(numero(l.get("Tarifa Final")) or ""),
        )
        for l in linhas
    ]
    cursor.executemany(
        "INSERT INTO tarifas_canal (canal, tipo_tarifa, limite,"
        " tarifa_inicial, tarifa_final) VALUES (?, ?, ?, ?, ?)",
        dados,
    )
    contagens["tarifas_canal"] = len(dados)

    # --- Valores fixos ----------------------------------------------------
    linhas = _ler(ARQUIVOS["valores_fixos"])
    dados = [
        (
            (l.get("Origem") or "").strip(),
            (l.get("Item") or "").strip(),
            (l.get("Canal") or "").strip() or None,
            str(numero(l.get("Valor")) or ""),
            (l.get("Condicao") or "sempre").strip(),
            (l.get("Observacao") or "").strip() or None,
        )
        for l in linhas
    ]
    cursor.executemany(
        "INSERT INTO valores_fixos (origem, item, canal, valor, condicao,"
        " observacao) VALUES (?, ?, ?, ?, ?, ?)",
        dados,
    )
    contagens["valores_fixos"] = len(dados)

    # --- Apelidos de canal (opcional) -------------------------------------
    caminho_apelidos = ARQUIVOS["apelidos_canal"]
    if caminho_apelidos.exists():
        dados = []
        for l in _ler(caminho_apelidos):
            captura_nome = (l.get("Canal na captura") or "").strip()
            if not captura_nome:
                continue
            dados.append((
                captura_nome,
                (l.get("Canal na tarifa") or "").strip() or None,
                (l.get("Observacao") or "").strip() or None,
            ))
        cursor.executemany(
            "INSERT OR REPLACE INTO apelidos_canal (canal_captura, canal_tarifa,"
            " observacao) VALUES (?, ?, ?)",
            dados,
        )
        contagens["apelidos_canal"] = len(dados)
    else:
        contagens["apelidos_canal"] = 0

    # --- Servicos fixos por emissor ---------------------------------------
    # Cruza o contratado com o valor fixo do item. O LEFT JOIN deixa o valor
    # nulo quando nao ha correspondencia, e a validacao aponta isso depois -
    # preencher com zero esconderia o cadastro faltando.
    linhas = _ler(ARQUIVOS["servicos_emissor"])
    fixos_por_item = {}
    for l in _ler(ARQUIVOS["valores_fixos"]):
        valor = numero(l.get("Valor"))
        for chave in ((l.get("Item") or ""), (l.get("Canal") or "")):
            chave = chave.strip().lower()
            if chave:
                fixos_por_item.setdefault(chave, valor)

    dados = []
    for l in linhas:
        codigo = (l.get("Codigo") or "").strip()
        servico = (l.get("Servico") or "").strip()
        if not codigo or not servico:
            continue
        valor = fixos_por_item.get(servico.lower())
        dados.append(
            (codigo, (l.get("Emissor") or "").strip() or None, servico,
             str(valor) if valor is not None else None, 1)
        )
    cursor.executemany(
        "INSERT OR IGNORE INTO servicos_fixos (codigo, emissor, servico,"
        " valor_fixo, ativo) VALUES (?, ?, ?, ?, ?)",
        dados,
    )
    contagens["servicos_fixos"] = len(dados)

    for tabela, n in contagens.items():
        log.info("carregado %-18s %3d linha(s)", tabela, n)

    return contagens


def validar(conexao) -> list[str]:
    """Inconsistencias que fariam o calculo errar em silencio."""
    avisos: list[str] = []
    cursor = conexao.cursor()

    cursor.execute("SELECT COUNT(*) FROM faixas_sic WHERE tipo_tarifa = 'fixa'")
    if cursor.fetchone()[0] != 1:
        avisos.append(
            "faixas_sic precisa de exatamente uma linha 'fixa' - ela define o"
            " limite e o valor ate o limite"
        )

    cursor.execute(
        "SELECT canal FROM tarifas_canal WHERE tipo_tarifa LIKE 'vari%'"
        " AND (limite IS NULL OR limite = '' OR tarifa_inicial IS NULL"
        "      OR tarifa_inicial = '')"
    )
    for (canal,) in cursor.fetchall():
        avisos.append(f"canal '{canal}': limite ou tarifa inicial ausente")

    cursor.execute(
        "SELECT codigo, servico FROM servicos_fixos WHERE valor_fixo IS NULL"
    )
    for codigo, servico in cursor.fetchall():
        avisos.append(
            f"emissor {codigo}: servico '{servico}' sem valor fixo"
            " correspondente em valores_fixos - nunca seria cobrado"
        )

    return avisos
