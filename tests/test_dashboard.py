"""Fase 1: achatamento da arvore e template variables."""

from __future__ import annotations

from ddcapture.dashboard import (
    achatar_widgets,
    substituir_template_vars,
    valores_template_vars,
)


def test_achata_grupos_aninhados(widgets):
    titulos = [w.titulo for w in widgets]

    # O widget dentro do grupo RDS, que por sua vez esta dentro de Infraestrutura AWS.
    assert "Conexoes RDS" in titulos
    # Os widgets de grupo em si nao viram Widget - nao tem valor proprio.
    assert "Infraestrutura AWS" not in titulos
    assert "RDS" not in titulos


def test_caminho_de_grupos_preserva_hierarquia(por_titulo):
    rds = por_titulo["Conexoes RDS"]
    assert rds.caminho_grupos == ["Infraestrutura AWS", "RDS"]
    # grupo_pai e o mais proximo, nao o mais externo.
    assert rds.grupo_pai == "RDS"

    cpu = por_titulo["CPU por host"]
    assert cpu.caminho_grupos == ["Infraestrutura AWS"]
    assert cpu.grupo_pai == "Infraestrutura AWS"


def test_widget_fora_de_grupo_nao_tem_pai(por_titulo):
    toplist = por_titulo["Erros 5xx por servico"]
    assert toplist.grupo_pai is None
    assert toplist.caminho_grupos == []


def test_widgets_sem_dado_sao_marcados(widgets):
    notas = [w for w in widgets if w.tipo == "note"]
    assert len(notas) == 1
    assert notas[0].sem_query is True
    # Mas continuam no inventario - o mapa do dashboard fica completo.
    assert notas[0] in widgets


def test_titulo_efetivo_cai_para_o_tipo(por_titulo):
    sem_titulo = por_titulo[""]
    assert sem_titulo.titulo == ""
    assert "timeseries" in sem_titulo.titulo_efetivo


def test_valores_template_vars_usa_defaults(valores_vars):
    assert valores_vars["env"] == "prod"
    # default '*' e mantido como coringa.
    assert valores_vars["service"] == "*"
    # default em lista pega o primeiro item.
    assert valores_vars["regiao"] == "sa-east-1"


def test_overrides_vencem_os_defaults(dashboard):
    valores = valores_template_vars(dashboard, {"env": "staging"})
    assert valores["env"] == "staging"
    assert valores["service"] == "*"


def test_substituicao_de_variaveis():
    valores = {"env": "prod", "service": "checkout"}

    assert (
        substituir_template_vars("avg:system.cpu{env:$env}", valores)
        == "avg:system.cpu{env:prod}"
    )
    assert (
        substituir_template_vars("avg:x{env:$env,service:$service}", valores)
        == "avg:x{env:prod,service:checkout}"
    )
    # Forma com chaves.
    assert substituir_template_vars("x{env:${env}}", valores) == "x{env:prod}"
    # Variavel desconhecida vira coringa em vez de deixar o '$' quebrar a query.
    assert substituir_template_vars("x{team:$team}", valores) == "x{team:*}"
    # Query sem variavel passa intacta.
    assert substituir_template_vars("avg:x{*}", valores) == "avg:x{*}"


def test_dashboard_vazio_nao_quebra():
    assert achatar_widgets({}) == []
    assert achatar_widgets({"widgets": []}) == []
