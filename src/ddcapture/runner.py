"""Orquestracao: dashboard -> widgets -> queries -> valores -> Measurements."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .categorize import Categorizador, mesclar_tags
from .client import DatadogClient
from .config import Config
from .dashboard import (
    achatar_widgets,
    prefixos_template_vars,
    valores_template_vars,
)
from .extractor import DATA_SOURCES_EVENTOS, DATA_SOURCES_METRICAS, extrair
from .models import Measurement, QuerySpec, Widget
from .resolvers import ValorBruto
from .resolvers import logs as resolver_logs
from .resolvers import metrics as resolver_metrics
from .resolvers import monitors as resolver_monitors
from .resolvers import slo as resolver_slo

log = logging.getLogger(__name__)


@dataclass
class Resultado:
    dashboard_id: str
    dashboard_titulo: str
    inicio_s: int
    fim_s: int
    widgets: list[Widget] = field(default_factory=list)
    specs: list[QuerySpec] = field(default_factory=list)
    medicoes: list[Measurement] = field(default_factory=list)
    # Template variables fixadas nesta execucao (--var). Entram no nome dos
    # arquivos: sem isso, capturas de emissores diferentes viram arquivos
    # indistinguiveis, so com o timestamp separando.
    filtros: dict[str, str] = field(default_factory=dict)
    # Nome curto para o arquivo (--rotulo). Substitui os filtros no nome quando
    # o valor do filtro nao serve, como '(1234 OR 234)'.
    rotulo: str = ""

    @property
    def falhas(self) -> list[Measurement]:
        return [m for m in self.medicoes if m.erro]

    @property
    def capturados(self) -> list[Measurement]:
        return [m for m in self.medicoes if m.erro is None]

    @property
    def sem_dados(self) -> list[Measurement]:
        """Campos preenchidos com 0 por ausencia de ocorrencias na janela."""
        return [m for m in self.medicoes if m.sem_dados and m.erro is None]

    def por_categoria(self) -> dict[str, list[Measurement]]:
        agrupado: dict[str, list[Measurement]] = {}
        for m in self.medicoes:
            agrupado.setdefault(m.categoria, []).append(m)
        return dict(sorted(agrupado.items()))


def preparar(
    dashboard: dict[str, Any],
    config: Config,
    inicio_s: int,
    fim_s: int,
    overrides_vars: dict[str, str] | None = None,
) -> Resultado:
    """Fase 1 + extracao das queries. Nao toca nas APIs de dados.

    E o que o --dry-run executa: da o inventario completo sem gastar rate limit.
    """
    widgets = achatar_widgets(dashboard)
    valores_vars = valores_template_vars(dashboard, overrides_vars)
    # Sem os prefixos, '--var codigoEmissor=1234' vira o token solto '1234' na
    # query - busca de texto livre em vez do filtro '@org:1234'. A query nao
    # falha, so devolve o numero errado.
    prefixos = prefixos_template_vars(dashboard)

    specs: list[QuerySpec] = []
    for widget in widgets:
        specs.extend(
            extrair(widget, valores_vars, config.agregador_padrao, prefixos)
        )

    return Resultado(
        dashboard_id=str(dashboard.get("id") or config.dashboard_id),
        dashboard_titulo=str(dashboard.get("title") or ""),
        inicio_s=inicio_s,
        fim_s=fim_s,
        widgets=widgets,
        specs=specs,
        filtros=dict(overrides_vars or {}),
    )


def capturar(
    client: DatadogClient,
    resultado: Resultado,
    config: Config,
) -> Resultado:
    """Fase 2 + 3: executa cada QuerySpec e monta os Measurements."""
    categorizador = Categorizador(config.categorias)
    chaves_tag = categorizador.tags_dimensao
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for indice, spec in enumerate(resultado.specs, start=1):
        log.info(
            "[%d/%d] %s (%s)",
            indice,
            len(resultado.specs),
            spec.widget.titulo_efetivo,
            spec.data_source,
        )
        tags_query = categorizador.extrair_tags(spec)
        for bruto in _resolver(client, spec, resultado.inicio_s, resultado.fim_s):
            resultado.medicoes.append(
                _montar(spec, bruto, resultado, categorizador, tags_query, chaves_tag, agora)
            )

    return resultado


def _resolver(
    client: DatadogClient, spec: QuerySpec, inicio_s: int, fim_s: int
) -> list[ValorBruto]:
    if spec.data_source == "slo":
        return resolver_slo.resolver(client, spec, inicio_s, fim_s)
    if spec.data_source == "monitors":
        return resolver_monitors.resolver(client, spec, inicio_s, fim_s)
    if spec.data_source in DATA_SOURCES_EVENTOS:
        return resolver_logs.resolver(client, spec, inicio_s, fim_s)
    if spec.data_source in DATA_SOURCES_METRICAS:
        return resolver_metrics.resolver(client, spec, inicio_s, fim_s)

    # data_source desconhecido: tenta a query unificada, que cobre a maioria.
    return resolver_metrics.resolver(client, spec, inicio_s, fim_s)


def _montar(
    spec: QuerySpec,
    bruto: ValorBruto,
    resultado: Resultado,
    categorizador: Categorizador,
    tags_query: dict[str, str],
    chaves_tag: list[str],
    agora: str,
) -> Measurement:
    widget = spec.widget
    classificacao = categorizador.classificar(spec)

    # Valor nulo sem erro = a query rodou e aquela celula veio vazia. Para uma
    # contagem isso significa zero ocorrencias, entao gravamos 0 e marcamos
    # sem_dados. Quando houve erro o valor fica nulo: nao sabemos quanto era.
    valor = bruto.valor
    sem_dados = bruto.sem_dados
    if valor is None and bruto.erro is None:
        valor = 0.0
        sem_dados = True

    return Measurement(
        dashboard_id=resultado.dashboard_id,
        dashboard_titulo=resultado.dashboard_titulo,
        grupo_pai=widget.grupo_pai,
        caminho_grupos=widget.caminho_grupos,
        widget_id=widget.widget_id,
        widget_titulo=widget.titulo_efetivo,
        widget_tipo=widget.tipo,
        nome_valor=_nome_final(widget, bruto, spec),
        data_source=spec.data_source,
        query=spec.descricao_query(),
        agregador=_agregador(spec),
        valor=valor,
        unidade=bruto.unidade,
        timestamp=bruto.timestamp,
        categoria=classificacao.categoria,
        categoria_origem=classificacao.origem,
        tags=mesclar_tags(tags_query, bruto.tags, chaves_tag),
        erro=bruto.erro,
        sem_dados=sem_dados,
        capturado_em=agora,
    )


def _nome_de_maquina(nome: str, spec: QuerySpec) -> bool:
    """O nome veio da API mas nao diz nada a um humano?

    Quando a formula do widget nao tem alias, a API devolve a propria expressao
    ('default_zero(query1)') como nome da coluna. Isso e ruido: o rotulo util e
    o titulo do widget. Comparar com as formulas e os nomes de query do spec e
    exato - nao ha adivinhacao por heuristica de texto.
    """
    if not nome:
        return True
    alvo = nome.strip()
    if any(alvo == str(f.get("formula", "")).strip() for f in spec.formulas):
        return True
    return any(alvo == str(q.get("name", "")).strip() for q in spec.queries)


def _nome_final(widget: Widget, bruto: ValorBruto, spec: QuerySpec) -> str:
    """Compoe 'titulo do widget | serie - escopo'.

    O titulo sozinho nao basta quando o widget mostra varias series; a serie
    sozinha perde o contexto de qual painel produziu o numero; e o escopo e o
    que distingue os valores de um widget quebrado por tag.
    """
    titulo = widget.titulo.strip()
    serie = (bruto.nome or "").strip()

    if serie and _nome_de_maquina(serie, spec):
        serie = ""
    if serie and titulo and serie.lower().startswith(titulo.lower()):
        titulo = ""

    partes = [p for p in (titulo, serie) if p]
    nome = " | ".join(partes) or widget.titulo_efetivo

    if bruto.tags:
        escopo = ", ".join(
            f"{k}:{v}" if v else k for k, v in sorted(bruto.tags.items())
        )
        return f"{nome} - {escopo}"
    return nome


def _agregador(spec: QuerySpec) -> str | None:
    for q in spec.queries:
        if q.get("aggregator"):
            return str(q["aggregator"])
    return None
