"""Fase 2b: executar QuerySpecs contra as APIs de dados.

Cada resolver recebe um QuerySpec e devolve ValorBruto - um valor com nome,
unidade e as tags do grupo da serie. Nomear e categorizar acontece depois,
em runner.py/categorize.py, para que os resolvers so cuidem de protocolo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValorBruto:
    """Um numero devolvido pela API, ainda sem categoria."""

    # Nome vindo da resposta: alias da formula, nome da query ou a metrica.
    nome: str
    valor: float | None
    unidade: str | None = None
    timestamp: int | None = None  # epoch em segundos
    # Tags do grupo da serie, ex.: {"host": "web-01", "env": "prod"}.
    tags: dict[str, str] = field(default_factory=dict)
    erro: str | None = None
    # A query rodou e nao achou nada na janela. Diferente de `erro`: aqui o
    # zero e a resposta certa (nenhuma ocorrencia), nao um dado que faltou.
    sem_dados: bool = False


def unidade_de(bloco: Any) -> str | None:
    """Extrai o rotulo da unidade das varias formas que a API devolve.

    Pode vir como lista [unidade_familia, unidade_por], com None nas posicoes
    nao usadas, ou como dict unico.
    """
    if not bloco:
        return None
    if isinstance(bloco, dict):
        return bloco.get("short_name") or bloco.get("name")
    if isinstance(bloco, list):
        partes = [unidade_de(b) for b in bloco if b]
        partes = [p for p in partes if p]
        if not partes:
            return None
        return "/".join(partes)
    return str(bloco)


def tags_de_lista(tags: Any) -> dict[str, str]:
    """Converte ['host:web-01', 'env:prod'] em dict.

    Tag sem ':' vira chave com valor vazio - o Datadog aceita tags simples.
    """
    saida: dict[str, str] = {}
    if not tags:
        return saida
    if isinstance(tags, str):
        tags = [tags]
    for t in tags:
        if not isinstance(t, str):
            continue
        chave, sep, valor = t.partition(":")
        saida[chave.strip()] = valor.strip() if sep else ""
    return saida
