"""Ponto de entrada da precificacao.

    python -m precificacao              carrega tarifas e precifica
    python -m precificacao --so-carga   so recarrega as tabelas dos CSV
    python -m precificacao -v           log detalhado

A captura NAO acontece aqui: rode antes o 3_capturar_emissores.bat. Este
comando so consome o que ja foi capturado.
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import captura, carga, relatorio, repositorio
from .configuracao import (
    ErroConfiguracao,
    carregar_banco,
    conectar,
    configurar_log,
)
from .precificador import precificar


def _nomes_emissores() -> dict[str, str]:
    """Codigo -> nome, so para rotular a saida.

    Arquivo opcional e fora do versionamento: sao dados da carteira.
    """
    caminho = carga.RAIZ / "config" / "emissores.txt"
    nomes: dict[str, str] = {}
    if not caminho.exists():
        return nomes
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        codigo, _, nome = linha.partition("=")
        codigo = codigo.strip()
        if codigo:
            nomes[codigo] = nome.strip() or codigo
    return nomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="precificacao",
        description="Precifica os servicos a partir das capturas do dashboard.",
    )
    parser.add_argument(
        "--so-carga",
        action="store_true",
        help="Recarrega as tabelas de preco dos CSV e sai, sem precificar.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log detalhado")
    args = parser.parse_args(argv)

    log = configurar_log(args.verbose)

    try:
        config = carregar_banco()
    except ErroConfiguracao as exc:
        log.error("configuracao invalida: %s", exc)
        return 2

    log.info("fonte de dados: %s", config.descricao_segura())

    try:
        with conectar(config) as conexao:
            # --- Carga das tabelas de preco ------------------------------
            contagens = carga.executar(conexao)
            avisos = carga.validar(conexao)
            for aviso in avisos:
                log.warning("consistencia: %s", aviso)

            if args.so_carga:
                total = sum(contagens.values())
                log.info("carga concluida: %d linha(s)", total)
                return 1 if avisos else 0

            # --- Captura ja produzida -------------------------------------
            try:
                usos = captura.carregar_todos()
            except captura.ErroCaptura as exc:
                log.error("%s", exc)
                return 1

            # --- Precificacao ---------------------------------------------
            nomes = _nomes_emissores()
            resultados = [
                precificar(conexao, uso, nomes.get(uso.codigo, uso.codigo))
                for uso in usos
            ]

    except ErroConfiguracao as exc:
        log.error("%s", exc)
        return 2
    except (carga.ErroCarga, repositorio.ErroRepositorio) as exc:
        log.error("%s", exc)
        return 1
    except Exception as exc:  # falha de banco, driver ausente, etc.
        log.error("falha no processamento: %s", exc)
        log.debug("detalhe", exc_info=True)
        return 1

    arquivos = [relatorio.gerar(r) for r in resultados]
    relatorio.resumo(resultados, arquivos)

    return 1 if any(r.erros for r in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
