"""Credenciais, conexao e logging.

Nada de negocio mora aqui: nenhum limite, nenhuma tarifa, nenhum preco. Isso
tudo vem das tabelas, via repositorio. Aqui so ficam onde esta o banco e como
chegar nele.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

MOTORES = ("sqlite", "postgres", "mysql")


class ErroConfiguracao(Exception):
    """Configuracao ausente ou invalida."""


@dataclass(frozen=True)
class ConfiguracaoBanco:
    """Como chegar no banco. Nunca logada nem impressa por inteiro."""

    motor: str
    nome: str
    host: str | None = None
    porta: int | None = None
    usuario: str | None = None
    senha: str | None = None

    @property
    def placeholder(self) -> str:
        """O marcador de parametro muda com o driver."""
        return "?" if self.motor == "sqlite" else "%s"

    def descricao_segura(self) -> str:
        """Identifica o destino sem revelar usuario nem senha."""
        if self.motor == "sqlite":
            return f"sqlite:{Path(self.nome).name}"
        return f"{self.motor}:{self.nome}@{self.host}:{self.porta}"


def carregar_banco() -> ConfiguracaoBanco:
    """Le a configuracao do banco do .env.

    Prefixo PRECOS_ para nao colidir com as variaveis do coletor, que vivem
    no mesmo .env.
    """
    load_dotenv(RAIZ / ".env")

    motor = (os.getenv("PRECOS_DB_ENGINE") or "sqlite").strip().lower()
    if motor not in MOTORES:
        raise ErroConfiguracao(
            f"PRECOS_DB_ENGINE invalido: {motor!r}. Use: {', '.join(MOTORES)}"
        )

    nome = (os.getenv("PRECOS_DB_NAME") or "").strip()

    if motor == "sqlite":
        # Caminho relativo e resolvido a partir da raiz do projeto, para o
        # resultado nao depender de onde o comando foi disparado.
        if not nome:
            raise ErroConfiguracao(
                "PRECOS_DB_NAME ausente. Para sqlite, e o caminho do arquivo."
            )
        caminho = Path(nome)
        if not caminho.is_absolute():
            caminho = RAIZ / caminho
        return ConfiguracaoBanco(motor=motor, nome=str(caminho))

    faltando = [
        chave
        for chave in ("PRECOS_DB_NAME", "PRECOS_DB_HOST", "PRECOS_DB_PORT",
                      "PRECOS_DB_USER", "PRECOS_DB_PASSWORD")
        if not (os.getenv(chave) or "").strip()
    ]
    if faltando:
        raise ErroConfiguracao(
            "Variaveis ausentes no .env: " + ", ".join(faltando)
        )

    porta_txt = os.getenv("PRECOS_DB_PORT", "").strip()
    try:
        porta = int(porta_txt)
    except ValueError:
        raise ErroConfiguracao(f"PRECOS_DB_PORT nao numerico: {porta_txt!r}") from None

    return ConfiguracaoBanco(
        motor=motor,
        nome=nome,
        host=os.getenv("PRECOS_DB_HOST", "").strip(),
        porta=porta,
        usuario=os.getenv("PRECOS_DB_USER", "").strip(),
        senha=os.getenv("PRECOS_DB_PASSWORD", ""),
    )


@contextmanager
def conectar(config: ConfiguracaoBanco) -> Iterator:
    """Abre a conexao e garante o fechamento.

    Commit so no fim, sem excecao; qualquer falha desfaz o lote inteiro -
    metade dos calculos gravados seria pior do que nenhum.
    """
    conexao = None
    try:
        if config.motor == "sqlite":
            import sqlite3

            conexao = sqlite3.connect(config.nome)
        elif config.motor == "mysql":
            import mysql.connector

            conexao = mysql.connector.connect(
                host=config.host,
                port=config.porta,
                database=config.nome,
                user=config.usuario,
                password=config.senha,
            )
        else:
            import psycopg2

            conexao = psycopg2.connect(
                host=config.host,
                port=config.porta,
                dbname=config.nome,
                user=config.usuario,
                password=config.senha,
            )

        yield conexao
        conexao.commit()

    except Exception:
        if conexao is not None:
            try:
                conexao.rollback()
            except Exception:
                logging.getLogger(__name__).warning(
                    "rollback tambem falhou", exc_info=True
                )
        raise
    finally:
        if conexao is not None:
            try:
                conexao.close()
            except Exception:
                pass


def configurar_log(verboso: bool = False) -> logging.Logger:
    """Log em console.

    Sem credencial, sem host, sem senha: o que identifica o banco sai por
    ConfiguracaoBanco.descricao_segura().
    """
    nivel = logging.DEBUG if verboso else logging.INFO
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("precificacao")
