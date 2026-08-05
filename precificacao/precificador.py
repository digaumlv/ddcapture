"""Orquestracao: junta captura, tarifas consultadas e regras de calculo.

Cada item precificado registra a tarifa consultada, a regra aplicada e o
resultado. Item que nao pode ser calculado entra com valor nulo e o motivo -
nunca com zero, que seria um valor financeiro inventado.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from . import calculo, repositorio
from .captura import UsoEmissor

log = logging.getLogger(__name__)


@dataclass
class Item:
    """Uma linha precificada."""

    emissor: str
    codigo: str
    servico: str
    tipo: str                      # SIC | FIXO | VARIAVEL
    quantidade: Decimal | None
    regra: str
    valor: Decimal | None
    erro: str | None = None

    @property
    def ok(self) -> bool:
        return self.erro is None and self.valor is not None


@dataclass
class ResultadoEmissor:
    codigo: str
    emissor: str
    janela: str
    itens: list[Item] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((i.valor for i in self.itens if i.ok), Decimal("0"))

    @property
    def erros(self) -> list[Item]:
        return [i for i in self.itens if not i.ok]

    def por_tipo(self, tipo: str) -> Decimal:
        return sum((i.valor for i in self.itens if i.ok and i.tipo == tipo), Decimal("0"))


def precificar(conexao, uso: UsoEmissor, nome_emissor: str) -> ResultadoEmissor:
    """Precifica um emissor: SIC, servicos fixos e servicos variaveis."""
    resultado = ResultadoEmissor(
        codigo=uso.codigo, emissor=nome_emissor, janela=uso.janela
    )

    # --- 1. Tabela de precos SIC ------------------------------------------
    parametros = repositorio.parametros_sic(conexao)
    try:
        memoria = calculo.calcular_sic(
            quantidade=uso.eventos,
            limite=parametros.limite,
            valor_ate_limite=parametros.valor_ate_limite,
            tarifa_excedente=parametros.tarifa_excedente,
        )
    except calculo.ErroCalculo as exc:
        log.error("emissor %s SIC: %s", uso.codigo, exc)
        resultado.itens.append(Item(
            emissor=nome_emissor, codigo=uso.codigo, servico="SIC Eventos",
            tipo="SIC", quantidade=uso.eventos, regra="-", valor=None,
            erro=str(exc),
        ))
    else:
        log.info(
            "emissor %s SIC: %s -> %s", uso.codigo, memoria.descrever(), memoria.valor
        )
        resultado.itens.append(Item(
            emissor=nome_emissor, codigo=uso.codigo, servico="SIC Eventos",
            tipo="SIC", quantidade=uso.eventos, regra=memoria.regra,
            valor=memoria.valor,
        ))

    # --- 2. Servicos fixos -------------------------------------------------
    contratados = repositorio.servicos_fixos(conexao, uso.codigo)
    condicoes = repositorio.condicao_por_item(conexao)
    uso_normalizado = {
        repositorio.normalizar(c): v for c, v in uso.canais_com_uso.items()
    }

    for chave, servico in sorted(contratados.items(), key=lambda kv: kv[1].servico):
        condicao = condicoes.get(chave, "sempre")
        volume = uso_normalizado.get(chave)

        if condicao == "acima_da_franquia":
            # Nao e valor fixo: cobra-se por evento no excedente, e isso ja
            # foi tratado na regra SIC.
            log.debug(
                "emissor %s: %s fora do fixo (condicao %s)",
                uso.codigo, servico.servico, condicao,
            )
            continue

        if condicao == "canal_com_uso" and not volume:
            log.info(
                "emissor %s: %s contratado mas sem uso no periodo - nao cobrado",
                uso.codigo, servico.servico,
            )
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo, servico=servico.servico,
                tipo="FIXO", quantidade=Decimal("0"),
                regra="nao cobrado - canal sem uso no periodo", valor=Decimal("0"),
            ))
            continue

        try:
            memoria = calculo.calcular_fixo(
                valor_fixo=servico.valor_fixo,
                ativo=servico.ativo,
                emissor=nome_emissor,
                servico=servico.servico,
            )
        except calculo.ErroCalculo as exc:
            log.error("emissor %s FIXO %s: %s", uso.codigo, servico.servico, exc)
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo, servico=servico.servico,
                tipo="FIXO", quantidade=volume, regra="-", valor=None, erro=str(exc),
            ))
        else:
            log.info(
                "emissor %s FIXO %s: %s -> %s",
                uso.codigo, servico.servico, memoria.descrever(), memoria.valor,
            )
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo, servico=servico.servico,
                tipo="FIXO", quantidade=volume, regra=memoria.regra,
                valor=memoria.valor,
            ))

    # --- 3. Servicos variaveis --------------------------------------------
    tarifas = repositorio.tarifas_por_canal(conexao)
    apelidos = repositorio.apelidos_canal(conexao)

    for canal, volume in sorted(uso.enviado_por_canal.items(), key=lambda kv: -kv[1]):
        chave_captura = repositorio.normalizar(canal)

        # Canal declarado como nao precificavel: a serie sobrepoe outra e
        # somar as duas contaria a mesma mensagem duas vezes.
        if chave_captura in apelidos and apelidos[chave_captura] is None:
            log.info(
                "emissor %s: canal '%s' ignorado por configuracao"
                " (sobrepoe outra serie)",
                uso.codigo, canal,
            )
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo, servico=canal,
                tipo="VARIAVEL", quantidade=volume,
                regra="ignorado por configuracao - sobrepoe outra serie",
                valor=Decimal("0"),
            ))
            continue

        # Apelido tem prioridade; depois o nome completo; depois so o canal.
        tarifa = None
        if chave_captura in apelidos:
            tarifa = tarifas.get(repositorio.normalizar(apelidos[chave_captura] or ""))
        if tarifa is None:
            chave = repositorio.normalizar(
                canal.split("/")[0].replace("(exceto ", "")
            )
            tarifa = tarifas.get(chave_captura) or tarifas.get(chave)

        if tarifa is None:
            motivo = f"canal '{canal}' sem tarifa cadastrada"
            log.error("emissor %s VARIAVEL: %s", uso.codigo, motivo)
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo, servico=canal,
                tipo="VARIAVEL", quantidade=volume, regra="-", valor=None,
                erro=motivo,
            ))
            continue

        try:
            memoria = calculo.calcular_variavel(
                quantidade=volume,
                limite=tarifa.limite,
                tarifa_inicial=tarifa.tarifa_inicial,
                tarifa_final=tarifa.tarifa_final,
            )
        except calculo.ErroCalculo as exc:
            log.error("emissor %s VARIAVEL %s: %s", uso.codigo, canal, exc)
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo, servico=canal,
                tipo="VARIAVEL", quantidade=volume, regra="-", valor=None,
                erro=str(exc),
            ))
        else:
            log.info(
                "emissor %s VARIAVEL %s (tarifa %s): %s -> %s",
                uso.codigo, canal, tarifa.canal, memoria.descrever(), memoria.valor,
            )
            resultado.itens.append(Item(
                emissor=nome_emissor, codigo=uso.codigo,
                servico=f"{canal} ({tarifa.canal})", tipo="VARIAVEL",
                quantidade=volume, regra=memoria.regra, valor=memoria.valor,
            ))

    log.info(
        "emissor %s: total %s (SIC %s | FIXO %s | VARIAVEL %s), %d erro(s)",
        uso.codigo, resultado.total, resultado.por_tipo("SIC"),
        resultado.por_tipo("FIXO"), resultado.por_tipo("VARIAVEL"),
        len(resultado.erros),
    )
    return resultado
