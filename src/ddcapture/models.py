"""Estruturas de dados que atravessam o pipeline.

O fluxo e: Widget (o que existe no dashboard) -> QuerySpec (o que da para
perguntar a API) -> Measurement (o valor capturado, ja nomeado e categorizado).
"""

from dataclasses import dataclass, field, asdict
from typing import Any


# Widgets que so tem conteudo visual - nao ha valor a capturar neles.
TIPOS_SEM_DADO = frozenset(
    {"note", "image", "free_text", "iframe", "distribution_list"}
)


@dataclass
class Widget:
    """Um widget achatado da arvore do dashboard."""

    widget_id: str
    tipo: str
    titulo: str
    # Titulo do widget de grupo que contem este. None no nivel raiz.
    grupo_pai: str | None
    # Caminho completo de grupos, do mais externo ao mais interno.
    caminho_grupos: list[str] = field(default_factory=list)
    # A definition crua, preservada para os extratores.
    definition: dict[str, Any] = field(default_factory=dict)

    @property
    def sem_query(self) -> bool:
        return self.tipo in TIPOS_SEM_DADO

    @property
    def titulo_efetivo(self) -> str:
        """Titulo utilizavel: cai para o grupo, depois para o tipo."""
        if self.titulo:
            return self.titulo
        if self.grupo_pai:
            return f"({self.grupo_pai})"
        return f"<{self.tipo} {self.widget_id}>"


@dataclass
class QuerySpec:
    """Uma unidade executavel extraida de um request de widget.

    Guarda tanto o payload pronto para a API v2 quanto os metadados necessarios
    para nomear e categorizar o resultado depois.
    """

    widget: Widget
    # Indice do request dentro de definition.requests - desambigua widgets
    # com varios requests.
    indice_request: int
    # metrics | logs | rum | events | slo | monitors | ...
    data_source: str
    # timeseries | scalar | event_list
    response_format: str
    # Queries no formato v2 (data_source/name/query), ja com template vars
    # substituidas e aggregator preenchido.
    queries: list[dict[str, Any]] = field(default_factory=list)
    # Formulas no formato v2 (formula/alias).
    formulas: list[dict[str, Any]] = field(default_factory=list)
    # Preenchido quando a origem e o formato legado requests[].q.
    query_legada: str | None = None
    # Campos especificos de resolvers nao-metricos (ex.: slo_id).
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def e_legada(self) -> bool:
        return self.query_legada is not None

    def descricao_query(self) -> str:
        """Texto da query para registro na saida.

        Nem toda fonte usa o campo `query`: logs e eventos guardam a busca em
        `search`, SLO e monitores nao tem query nenhuma. Sem estes fallbacks a
        coluna `query` sairia vazia justamente nessas linhas.
        """
        if self.query_legada:
            return self.query_legada

        partes: list[str] = []
        for q in self.queries:
            if q.get("query"):
                partes.append(str(q["query"]))
                continue
            busca = q.get("search")
            if isinstance(busca, dict) and busca.get("query"):
                agregacao = (q.get("compute") or {}).get("aggregation") or "count"
                partes.append(f"{agregacao}({busca['query']})")
        if partes:
            return " ; ".join(partes)

        if self.data_source == "slo" and self.extra.get("slo_id"):
            return f"slo:{self.extra['slo_id']}"
        if self.data_source == "monitors":
            return f"monitors:{self.extra.get('query') or '*'}"
        return ""


@dataclass
class Measurement:
    """Um valor capturado, identificado pelo nome e categorizado."""

    dashboard_id: str
    dashboard_titulo: str

    grupo_pai: str | None
    caminho_grupos: list[str]
    widget_id: str
    widget_titulo: str
    widget_tipo: str

    # O "nome" do valor: alias da formula > nome da query > query crua,
    # acrescido do escopo da serie quando ha quebra por tag.
    nome_valor: str

    data_source: str
    query: str
    agregador: str | None

    valor: float | None
    unidade: str | None
    timestamp: int | None  # epoch em segundos, quando aplicavel

    categoria: str
    categoria_origem: str  # grupo | palavra-chave | namespace | fallback

    tags: dict[str, str] = field(default_factory=dict)
    erro: str | None = None
    # True quando a query rodou mas nao achou nada: o valor 0 e a resposta,
    # nao um dado que faltou. Separa "zero ocorrencias" de "nao consegui ler".
    sem_dados: bool = False
    capturado_em: str = ""

    def para_linha(self, chaves_tag: list[str]) -> dict[str, Any]:
        """Versao achatada para CSV/XLSX/SQLite."""
        d = asdict(self)
        d["caminho_grupos"] = " > ".join(self.caminho_grupos)
        d.pop("tags")
        for chave in chaves_tag:
            d[chave] = self.tags.get(chave, "")
        return d
