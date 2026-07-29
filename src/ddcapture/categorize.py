"""Fase 3: categorizacao automatica, em cascata.

A primeira camada que resolver define a categoria; `origem` registra qual foi,
de modo que toda classificacao seja auditavel na saida.

  1. grupo   - titulo do widget de grupo que contem o widget
  2. palavra-chave - regex do categorias.yaml contra o titulo do widget
  3. namespace - prefixo do nome da metrica
  4. fallback

Tags (env, service, team) NAO competem na cascata: sao dimensoes ortogonais,
extraidas do escopo da query e gravadas em colunas proprias.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .extractor import nome_metrica
from .models import QuerySpec

# tag:valor dentro do escopo {...} de uma query classica.
_TAG_NO_ESCOPO = re.compile(r"([a-zA-Z0-9_.\-/]+)\s*:\s*([a-zA-Z0-9_.\-/*]+)")
# Conteudo entre chaves: escopo {...} e agrupamento by {...}.
_ESCOPO = re.compile(r"\{([^}]*)\}")


@dataclass(frozen=True)
class Classificacao:
    categoria: str
    origem: str  # grupo | palavra-chave | namespace | fallback


def normalizar(texto: str) -> str:
    """Minusculas e sem acento - as regras do YAML sao escritas assim."""
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.lower().strip()


class Categorizador:
    def __init__(self, regras: dict[str, Any]):
        self.fallback = str(regras.get("fallback") or "sem-categoria")
        self.tags_dimensao = list(regras.get("tags_dimensao") or [])

        self._palavras: list[tuple[str, re.Pattern[str]]] = []
        for regra in regras.get("palavras_chave") or []:
            categoria = str(regra.get("categoria") or "").strip()
            padrao = str(regra.get("padrao") or "").strip()
            if not categoria or not padrao:
                continue
            self._palavras.append((categoria, re.compile(padrao, re.IGNORECASE)))

        # Ordena por prefixo mais longo: 'aws.rds' precisa vencer 'aws'.
        namespaces = regras.get("namespaces") or {}
        self._namespaces: list[tuple[str, str]] = sorted(
            ((str(k).lower(), str(v)) for k, v in namespaces.items()),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )

    def classificar(self, spec: QuerySpec) -> Classificacao:
        widget = spec.widget

        # 1. Estrutura do proprio dashboard - custo zero de configuracao.
        if widget.grupo_pai:
            return Classificacao(widget.grupo_pai.strip(), "grupo")

        # 2. Palavra-chave, contra o TITULO do widget e nada mais. Usar o nome
        # do valor aqui seria tentador, mas ele carrega o escopo da serie
        # ('... - host:web-01') e a tag passaria a decidir a categoria.
        alvo = normalizar(widget.titulo)
        if alvo:
            for categoria, padrao in self._palavras:
                if padrao.search(alvo):
                    return Classificacao(categoria, "palavra-chave")

        # 3. Namespace da metrica.
        categoria = self._por_namespace(spec)
        if categoria:
            return Classificacao(categoria, "namespace")

        return Classificacao(self.fallback, "fallback")

    def _por_namespace(self, spec: QuerySpec) -> str | None:
        for metrica in self._metricas(spec):
            alvo = metrica.lower()
            for prefixo, categoria in self._namespaces:
                if alvo == prefixo or alvo.startswith(prefixo + "."):
                    return categoria
        return None

    @staticmethod
    def _metricas(spec: QuerySpec) -> list[str]:
        if spec.query_legada:
            return [nome_metrica(spec.query_legada)]
        nomes = []
        for q in spec.queries:
            texto = str(q.get("query") or "")
            if texto:
                nomes.append(nome_metrica(texto))
        return [n for n in nomes if n]

    def extrair_tags(self, spec: QuerySpec) -> dict[str, str]:
        """Tags do escopo da query, limitadas as chaves de dimensao configuradas.

        Um valor '*' (coringa) e descartado: nao identifica nada.
        """
        if not self.tags_dimensao:
            return {}

        encontradas: dict[str, str] = {}
        for texto in self._textos_de_query(spec):
            for bloco in _ESCOPO.findall(texto):
                for chave, valor in _TAG_NO_ESCOPO.findall(bloco):
                    if chave in self.tags_dimensao and valor != "*":
                        encontradas.setdefault(chave, valor)
        return encontradas

    @staticmethod
    def _textos_de_query(spec: QuerySpec) -> list[str]:
        if spec.query_legada:
            return [spec.query_legada]
        textos = []
        for q in spec.queries:
            if q.get("query"):
                textos.append(str(q["query"]))
            busca = (q.get("search") or {}).get("query") if isinstance(q.get("search"), dict) else None
            if busca:
                textos.append(str(busca))
        return textos


def mesclar_tags(
    tags_query: dict[str, str],
    tags_serie: dict[str, str],
    chaves: list[str],
) -> dict[str, str]:
    """Une tags do escopo da query com as do grupo da serie.

    As da serie vencem: quando a query pede `by {service}`, o valor concreto de
    cada linha e mais especifico do que o filtro do escopo.
    """
    saida = {k: v for k, v in tags_query.items() if k in chaves}
    for chave in chaves:
        if tags_serie.get(chave):
            saida[chave] = tags_serie[chave]
    return saida
