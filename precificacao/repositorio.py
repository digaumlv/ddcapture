"""Consulta de tarifas, limites e valores fixos.

Camada unica que fala com o banco para buscar preco. O modulo de calculo
recebe o que sai daqui - nao faz consulta e nao conhece tabela.

Todo valor de negocio vem de tabela. Nao ha limite, tarifa ou preco escrito
neste arquivo: quem define e o CSV carregado por carga.py.

Consultas sempre parametrizadas. Os identificadores (nome de tabela e coluna)
sao constantes deste pacote, nunca entrada externa - nao ha superficie de
SQL injection.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

log = logging.getLogger(__name__)


class ErroRepositorio(Exception):
    """Dado de preco ausente ou inconsistente na fonte."""


@dataclass(frozen=True)
class ParametrosSic:
    limite: Decimal
    valor_ate_limite: Decimal
    tarifa_excedente: Decimal | None


@dataclass(frozen=True)
class TarifaCanal:
    canal: str
    limite: Decimal
    tarifa_inicial: Decimal
    tarifa_final: Decimal | None


@dataclass(frozen=True)
class ServicoFixo:
    codigo: str
    emissor: str | None
    servico: str
    valor_fixo: Decimal | None
    ativo: bool


def normalizar(texto: str) -> str:
    """'WhatsApp', 'Whats-App', 'whatsapp ' -> 'whatsapp'.

    O canal vem do Datadog e o preco vem do CSV; os dois nomes raramente
    coincidem caractere a caractere.
    """
    if not texto:
        return ""
    sem_acento = (
        unicodedata.normalize("NFKD", str(texto))
        .encode("ascii", "ignore")
        .decode()
    )
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def _dec(valor, campo: str) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor))
    except Exception:
        raise ErroRepositorio(f"{campo} nao numerico na fonte: {valor!r}") from None


def parametros_sic(conexao) -> ParametrosSic:
    """Limite, valor dentro do limite e tarifa do excedente, todos da tabela.

    A linha 'fixa' define o limite (faixa_final) e o valor cobrado ate ele.
    A tarifa do excedente vem da primeira faixa variavel - a que passa a
    valer logo acima do limite.
    """
    cursor = conexao.cursor()

    cursor.execute(
        "SELECT faixa_final, tarifa_nao_financeiro FROM faixas_sic"
        " WHERE tipo_tarifa = 'fixa'"
    )
    linha = cursor.fetchone()
    if linha is None:
        raise ErroRepositorio(
            "faixas_sic nao tem linha 'fixa' - sem ela nao ha limite nem"
            " valor base para o SIC"
        )

    limite = _dec(linha[0], "limite SIC")
    valor = _dec(linha[1], "valor SIC ate o limite")
    if limite is None or valor is None:
        raise ErroRepositorio("linha 'fixa' de faixas_sic incompleta")

    cursor.execute(
        "SELECT tarifa_nao_financeiro FROM faixas_sic"
        " WHERE tipo_tarifa LIKE 'vari%' ORDER BY faixa_final LIMIT 1"
    )
    linha_var = cursor.fetchone()
    tarifa = _dec(linha_var[0], "tarifa do excedente SIC") if linha_var else None

    log.info(
        "SIC consultado: limite=%s valor_ate_limite=%s tarifa_excedente=%s",
        f"{limite:,.0f}", valor, tarifa,
    )
    return ParametrosSic(limite=limite, valor_ate_limite=valor, tarifa_excedente=tarifa)


def tarifas_por_canal(conexao) -> dict[str, TarifaCanal]:
    """Tarifas do broker de comunicacao, indexadas por canal normalizado."""
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT canal, limite, tarifa_inicial, tarifa_final FROM tarifas_canal"
        " WHERE tipo_tarifa LIKE 'vari%'"
    )

    tarifas: dict[str, TarifaCanal] = {}
    for canal, limite, t_ini, t_fim in cursor.fetchall():
        chave = normalizar(canal)
        if not chave:
            continue
        lim = _dec(limite, f"limite do canal {canal}")
        ini = _dec(t_ini, f"tarifa inicial do canal {canal}")
        if lim is None or ini is None:
            log.warning("canal %s ignorado: limite ou tarifa inicial ausente", canal)
            continue
        tarifas[chave] = TarifaCanal(
            canal=canal,
            limite=lim,
            tarifa_inicial=ini,
            tarifa_final=_dec(t_fim, f"tarifa final do canal {canal}"),
        )

    log.info("tarifas de canal consultadas: %d", len(tarifas))
    for t in sorted(tarifas.values(), key=lambda x: x.canal):
        log.debug(
            "  %-24s limite=%s inicial=%s final=%s",
            t.canal, f"{t.limite:,.0f}", t.tarifa_inicial, t.tarifa_final,
        )
    return tarifas


def apelidos_canal(conexao) -> dict[str, str | None]:
    """Nome do canal na captura -> nome na tabela de tarifas.

    Valor None marca canal a NAO precificar. E assim que se declara, por
    dado, que uma serie sobrepoe outra - decisao de negocio que nao deve
    virar heuristica no codigo.
    """
    cursor = conexao.cursor()
    try:
        cursor.execute("SELECT canal_captura, canal_tarifa FROM apelidos_canal")
    except Exception:
        # Tabela opcional: sem ela o casamento e so por nome normalizado.
        return {}

    mapa: dict[str, str | None] = {}
    for captura_nome, tarifa_nome in cursor.fetchall():
        chave = normalizar(captura_nome)
        if chave:
            mapa[chave] = tarifa_nome
    log.info("apelidos de canal consultados: %d", len(mapa))
    return mapa


def servicos_fixos(conexao, codigo_emissor: str) -> dict[str, ServicoFixo]:
    """Servicos fixos contratados por um emissor, indexados pelo servico."""
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT codigo, emissor, servico, valor_fixo, ativo FROM servicos_fixos"
        " WHERE codigo = ?".replace("?", _ph(conexao)),
        (codigo_emissor,),
    )

    encontrados: dict[str, ServicoFixo] = {}
    for codigo, emissor, servico, valor, ativo in cursor.fetchall():
        encontrados[normalizar(servico)] = ServicoFixo(
            codigo=codigo,
            emissor=emissor,
            servico=servico,
            valor_fixo=_dec(valor, f"valor fixo de {servico}"),
            ativo=bool(ativo),
        )

    if not encontrados:
        log.warning(
            "emissor %s nao tem servico fixo cadastrado - nenhum valor fixo"
            " sera cobrado para ele",
            codigo_emissor,
        )
    else:
        log.info(
            "emissor %s: %d servico(s) fixo(s) - %s",
            codigo_emissor,
            len(encontrados),
            ", ".join(sorted(s.servico for s in encontrados.values())),
        )
    return encontrados


def condicao_por_item(conexao) -> dict[str, str]:
    """Condicao de cobranca de cada item fixo, vinda da tabela.

        sempre             cobra independente de uso
        canal_com_uso      so cobra se o canal teve evento no periodo
        acima_da_franquia  nunca entra no fixo
    """
    cursor = conexao.cursor()
    cursor.execute("SELECT item, canal, condicao FROM valores_fixos")

    condicoes: dict[str, str] = {}
    for item, canal, condicao in cursor.fetchall():
        for nome in (item, canal):
            chave = normalizar(nome or "")
            if chave:
                condicoes.setdefault(chave, condicao)
    return condicoes


def valores_sempre_devidos(conexao) -> list[tuple[str, Decimal]]:
    """Itens fixos cobrados independente de uso ou de contrato."""
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT item, valor FROM valores_fixos WHERE condicao = ?"
        .replace("?", _ph(conexao)),
        ("sempre",),
    )
    itens = []
    for item, valor in cursor.fetchall():
        v = _dec(valor, f"valor fixo de {item}")
        if v is not None:
            itens.append((item, v))
            log.info("fixo sempre devido: %s = %s", item, v)
    return itens


def _ph(conexao) -> str:
    """Placeholder do driver: '?' no sqlite, '%s' nos demais."""
    return "?" if type(conexao).__module__.startswith("sqlite3") else "%s"
