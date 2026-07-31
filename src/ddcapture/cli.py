"""Interface de linha de comando."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .categorize import Categorizador, normalizar
from .client import DatadogClient, ErroApi
from .config import ErroConfig, carregar, resolver_instante
from .dashboard import (
    buscar_dashboard,
    carregar_dashboard_de_arquivo,
    listar_dashboards,
    valores_template_vars,
)
from .runner import capturar, preparar
from .sinks import gravar_todos

# Formato de janela relativa aceito na linha de comando: -15m, 15m, -1h, 7d...
_RELATIVO_CLI = re.compile(r"^-?\d+[smhdw]$")


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ddcapture",
        description=(
            "Captura os widgets de um dashboard do Datadog e os valores dentro deles, "
            "nomeados e categorizados automaticamente."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python -m ddcapture --listar\n"
            "  python -m ddcapture --dashboard-id abc-def-ghi --dry-run\n"
            "  python -m ddcapture --dashboard-id abc-def-ghi --from -15m\n"
            "  python -m ddcapture --dashboard-id abc-def-ghi --var env=prod --var service=checkout\n"
            "  python -m ddcapture --arquivo dashboard.json --dry-run   # sem credenciais\n"
        ),
    )
    p.add_argument("--dashboard-id", help="ID do dashboard (padrao: settings.yaml)")
    p.add_argument(
        "--from",
        dest="inicio",
        metavar="INICIO",
        help="Inicio: -1h, -7d, 01/07, 01/07/2026, 01/07 08:30, 2026-07-01, epoch",
    )
    p.add_argument(
        "--to",
        dest="fim",
        metavar="FIM",
        help="Fim: now, 31/07, 31/07/2026 18:00, epoch. Data sem hora = dia inteiro.",
    )
    p.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="CHAVE=VALOR",
        help="Sobrescreve uma template variable. Repetivel.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="So inventaria widgets e queries. Nao consulta dados nem grava arquivos.",
    )
    p.add_argument(
        "--arquivo",
        type=Path,
        help="Le a definicao de um JSON local em vez da API. Util com --dry-run.",
    )
    p.add_argument("--listar", action="store_true", help="Lista os dashboards da conta e sai.")
    p.add_argument(
        "--buscar",
        metavar="TEXTO",
        help="Lista so os dashboards cujo titulo contem TEXTO (ignora acento e caixa).",
    )
    p.add_argument(
        "--validar",
        action="store_true",
        help="Testa as credenciais do .env contra a API e sai.",
    )
    p.add_argument(
        "--rotulo",
        metavar="TEXTO",
        help="Nome curto no arquivo de saida. Use quando o valor do --var nao "
             "servir de nome, ex.: --var \"codigoEmissor=(1234 OR 234)\" --rotulo 1234",
    )
    p.add_argument("--saida", type=Path, help="Diretorio de saida (padrao: settings.yaml)")
    p.add_argument("-v", "--verbose", action="store_true", help="Log detalhado")
    return p


def _normalizar_argv(argv: list[str]) -> list[str]:
    """Cola '--from -15m' em '--from=-15m'.

    O argparse le qualquer token iniciado por '-' como uma nova flag, entao
    '--from -15m' falha com 'expected one argument'. Como janela e sempre para
    tras, a forma com hifen e a que o usuario escreve naturalmente.
    """
    saida: list[str] = []
    i = 0
    while i < len(argv):
        atual = argv[i]
        proximo = argv[i + 1] if i + 1 < len(argv) else None
        if (
            atual in ("--from", "--to")
            and proximo is not None
            and _RELATIVO_CLI.match(proximo)
        ):
            saida.append(f"{atual}={proximo}")
            i += 2
            continue
        saida.append(atual)
        i += 1
    return saida


def main(argv: list[str] | None = None) -> int:
    argv_bruto = list(sys.argv[1:] if argv is None else argv)
    args = montar_parser().parse_args(_normalizar_argv(argv_bruto))
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    # Sem credenciais so da para trabalhar offline, a partir de um JSON local.
    offline = bool(args.arquivo)

    try:
        config = carregar(exigir_credenciais=not offline)
    except ErroConfig as exc:
        print(f"Erro de configuracao: {exc}", file=sys.stderr)
        return 2

    if args.saida:
        config.saida_dir = args.saida

    client = None
    if config.credenciais:
        client = DatadogClient(
            config.credenciais,
            timeout_s=config.http_timeout_s,
            max_tentativas=config.http_max_tentativas,
            backoff_base_s=config.http_backoff_base_s,
        )

    if args.validar:
        return _validar(client, config)

    if args.listar or args.buscar:
        return _listar(client, args.buscar)

    dashboard_id = args.dashboard_id or config.dashboard_id
    if not offline and not dashboard_id:
        # Sem argumentos E sem dashboard configurado: quem chegou aqui
        # provavelmente deu duplo clique e nao sabe o que fazer. Ajuda, nao erro.
        if not argv_bruto:
            _imprimir_ajuda_curta()
            return 0
        print(
            "Informe o dashboard com --dashboard-id ou preencha dashboard_id em "
            "config/settings.local.yaml. Use --buscar TEXTO para descobrir o ID.",
            file=sys.stderr,
        )
        return 2

    if not argv_bruto:
        print(f"Usando o dashboard do settings: {dashboard_id}\n")

    try:
        if offline:
            dashboard = carregar_dashboard_de_arquivo(args.arquivo)
        else:
            dashboard = buscar_dashboard(client, dashboard_id)
    except ErroApi as exc:
        print(f"Erro ao buscar o dashboard: {exc}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(f"Erro ao ler {args.arquivo}: {exc}", file=sys.stderr)
        return 1

    utc = config.janela_em_utc
    try:
        inicio_s = resolver_instante(args.inicio or config.janela_from, utc=utc)
        # fim_do_dia: '--to 31/07' sem hora significa o dia 31 inteiro,
        # nao a virada da meia-noite que o deixaria de fora.
        fim_s = resolver_instante(
            args.fim or config.janela_to, fim_do_dia=True, utc=utc
        )
    except ErroConfig as exc:
        print(f"Janela invalida: {exc}", file=sys.stderr)
        return 2

    if inicio_s >= fim_s:
        print("Janela invalida: --from precisa ser anterior a --to.", file=sys.stderr)
        return 2

    if not args.dry_run:
        print(f"Janela: {_formatar_janela(inicio_s, fim_s, utc)}\n")

    config.dashboard_id = dashboard_id or str(dashboard.get("id") or "")
    resultado = preparar(dashboard, config, inicio_s, fim_s, _overrides(args.var))
    resultado.rotulo = args.rotulo or ""

    if args.dry_run:
        _imprimir_dry_run(resultado, config, dashboard, args.var)
        return 0

    if client is None:
        print(
            "--arquivo sem credenciais so funciona com --dry-run. "
            "Preencha o .env para consultar valores.",
            file=sys.stderr,
        )
        return 2

    capturar(client, resultado, config)
    escritos = gravar_todos(resultado, config)
    _imprimir_resumo(resultado, escritos)

    return 1 if resultado.falhas and not resultado.capturados else 0


def _imprimir_ajuda_curta() -> None:
    """Mostrada quando nao ha argumentos nem dashboard configurado."""
    print(
        """
  ddcapture - captura widgets e valores de dashboards do Datadog

  Para rodar sem argumentos, defina o dashboard uma vez:

      copy config\\settings.local.yaml.example config\\settings.local.yaml

  e preencha o dashboard_id. Depois basta:

      ddcapture.bat

  Comandos:

    ddcapture.bat --validar
        Testa se as chaves do .env funcionam no site configurado.

    ddcapture.bat --buscar TEXTO
        Lista os dashboards com TEXTO no titulo, com o ID de cada um.

    ddcapture.bat --dashboard-id ID --dry-run
        Inventario de widgets e queries. NAO consulta dados nem grava
        arquivos - use para conferir antes de gastar rate limit.

    ddcapture.bat --dashboard-id ID --from 01/07 --to 31/07
        Captura os valores e grava em out\\.

  Janelas: -15m, -1h, -7d, 01/07, 01/07/2026, now ou epoch.
  Lista completa de opcoes: ddcapture.bat --help
"""
    )


def _formatar_janela(inicio_s: int, fim_s: int, utc: bool = False) -> str:
    """Mostra a janela no mesmo fuso em que foi interpretada.

    Exibir em local uma janela lida em UTC (ou o contrario) esconde justamente
    o deslocamento que o fuso causa - que e o erro que se quer poder ver.
    """
    fmt = "%d/%m/%Y %H:%M:%S"
    tz = timezone.utc if utc else None
    inicio = datetime.fromtimestamp(inicio_s, tz).strftime(fmt)
    fim = datetime.fromtimestamp(fim_s, tz).strftime(fmt)
    dias = (fim_s - inicio_s) / 86400
    return f"{inicio}  ate  {fim}  {'UTC' if utc else 'local'}   ({dias:.1f} dias)"


def _mascarar(chave: str) -> str:
    """Mostra so o suficiente para identificar a chave, sem expor o segredo."""
    if len(chave) <= 8:
        return "*" * len(chave)
    return f"{chave[:4]}...{chave[-4:]} ({len(chave)} caracteres)"


def _validar(client: DatadogClient | None, config) -> int:
    if client is None:
        print("--validar precisa das credenciais no .env.", file=sys.stderr)
        return 2

    cred = config.credenciais
    print(f"Site:    {cred.site}  ->  {cred.base_url}")
    print(f"API key: {_mascarar(cred.api_key)}")
    print(f"APP key: {_mascarar(cred.app_key)}\n")

    try:
        api_ok = client.validar_api_key()
    except ErroApi as exc:
        print(f"[X] Nao foi possivel validar a API key: {exc}", file=sys.stderr)
        return 1

    print(f"[{'OK' if api_ok else 'X '}] API key {'valida' if api_ok else 'INVALIDA'}")
    if not api_ok:
        print(
            "\n    A API key nao foi reconhecida neste site. Verifique se ela foi criada "
            f"em {cred.site} - uma chave de outro site sempre da invalida aqui.",
            file=sys.stderr,
        )
        return 1

    try:
        app_ok, detalhe = client.validar_app_key()
    except ErroApi as exc:
        print(f"[X] Nao foi possivel validar a application key: {exc}", file=sys.stderr)
        return 1

    print(f"[{'OK' if app_ok else 'X '}] Application key {'valida' if app_ok else 'REJEITADA'} - {detalhe}")
    if not app_ok:
        print(
            "\n    Confira se a application key existe neste site e tem o escopo "
            "dashboards_read. Para logs/SLO/monitores adicione tambem "
            "logs_read_data, slos_read e monitors_read.",
            file=sys.stderr,
        )
        return 1

    print("\nCredenciais OK. Proximo passo: ddcapture.bat --buscar <parte do titulo>")
    return 0


def _listar(client: DatadogClient | None, filtro: str | None = None) -> int:
    if client is None:
        print("--listar precisa de credenciais no .env.", file=sys.stderr)
        return 2
    try:
        dashboards = listar_dashboards(client)
    except ErroApi as exc:
        print(f"Erro ao listar dashboards: {exc}", file=sys.stderr)
        return 1

    total = len(dashboards)
    if filtro:
        alvo = normalizar(filtro)
        dashboards = [d for d in dashboards if alvo in normalizar(str(d.get("title") or ""))]

    for d in sorted(dashboards, key=lambda x: str(x.get("title") or "")):
        print(f"{str(d.get('id') or ''):<24} {d.get('title') or ''}")

    if filtro:
        print(f"\n{len(dashboards)} de {total} dashboard(s) com {filtro!r} no titulo.")
        if not dashboards:
            print("Nenhum encontrado - tente um trecho menor do titulo.")
    else:
        print(f"\n{total} dashboard(s).")
    return 0


def _overrides(pares: list[str]) -> dict[str, str]:
    saida: dict[str, str] = {}
    for par in pares:
        chave, sep, valor = par.partition("=")
        if not sep:
            print(f"Ignorando --var {par!r}: use o formato chave=valor.", file=sys.stderr)
            continue
        saida[chave.strip()] = valor.strip()
    return saida


def _imprimir_dry_run(resultado, config, dashboard, vars_cli: list[str]) -> None:
    print(f"Dashboard: {resultado.dashboard_titulo} ({resultado.dashboard_id})")

    valores_vars = valores_template_vars(dashboard, _overrides(vars_cli))
    if valores_vars:
        aplicadas = ", ".join(f"${k}={v}" for k, v in sorted(valores_vars.items()))
        print(f"Template variables: {aplicadas}")

    sem_query = [w for w in resultado.widgets if w.sem_query]
    print(
        f"\nWidgets: {len(resultado.widgets)} "
        f"({len(sem_query)} sem dado) | Queries a executar: {len(resultado.specs)}\n"
    )

    categorizador = Categorizador(config.categorias)
    specs_por_widget: dict[str, list] = {}
    for spec in resultado.specs:
        specs_por_widget.setdefault(spec.widget.widget_id, []).append(spec)

    grupo_atual = object()
    for widget in resultado.widgets:
        caminho = " > ".join(widget.caminho_grupos) or "(sem grupo)"
        if caminho != grupo_atual:
            print(f"[{caminho}]")
            grupo_atual = caminho

        specs = specs_por_widget.get(widget.widget_id, [])
        if widget.sem_query:
            print(f"  - {widget.titulo_efetivo}  ({widget.tipo}, sem dado)")
            continue
        if not specs:
            print(f"  - {widget.titulo_efetivo}  ({widget.tipo}, NENHUMA QUERY EXTRAIDA)")
            continue

        classificacao = categorizador.classificar(specs[0])
        print(
            f"  - {widget.titulo_efetivo}  ({widget.tipo})"
            f"  -> {classificacao.categoria} [{classificacao.origem}]"
        )
        for spec in specs:
            tags = categorizador.extrair_tags(spec)
            sufixo = f"  tags={tags}" if tags else ""
            print(f"      {spec.data_source}/{spec.response_format}: {spec.descricao_query()}{sufixo}")

    print("\n(dry-run: nenhuma query de dados foi executada, nenhum arquivo gravado)")


def _imprimir_resumo(resultado, escritos: list[Path]) -> None:
    print(f"\nDashboard: {resultado.dashboard_titulo} ({resultado.dashboard_id})")
    print(
        f"Widgets: {len(resultado.widgets)} | Queries: {len(resultado.specs)} | "
        f"Valores: {len(resultado.capturados)} | Falhas: {len(resultado.falhas)}"
    )
    if resultado.sem_dados:
        print(
            f"  ({len(resultado.sem_dados)} campo(s) sem ocorrencias na janela, "
            "preenchidos com 0)"
        )

    print("\nPor categoria:")
    for categoria, medicoes in resultado.por_categoria().items():
        ok = sum(1 for m in medicoes if m.erro is None)
        origens = {m.categoria_origem for m in medicoes}
        print(f"  {categoria:<28} {ok:>4} valor(es)  [{', '.join(sorted(origens))}]")

    if resultado.falhas:
        print(f"\n{len(resultado.falhas)} falha(s):")
        for m in resultado.falhas[:15]:
            print(f"  - {m.widget_titulo} | {m.nome_valor}: {m.erro}")
        if len(resultado.falhas) > 15:
            print(f"  ... e mais {len(resultado.falhas) - 15}. Veja a coluna 'erro' na saida.")

    print("\nArquivos gravados:")
    for caminho in escritos:
        print(f"  {caminho}")


if __name__ == "__main__":
    raise SystemExit(main())
