"""As tres regras de calculo.

Este modulo nao conhece banco nem Datadog. Recebe Decimal ja consultado e
devolve Decimal - o que permite testar as regras sem rede e sem banco, e
garante que nenhum valor de negocio esteja escrito aqui: limites, tarifas e
precos chegam por parametro, vindos do repositorio.

Tudo em Decimal. Em float, 1.000.000 x 0,07 e exato mas 0,1 + 0,2 nao e, e o
erro se acumula em lote. O arredondamento acontece so no final, com
ROUND_HALF_UP - o round() nativo do Python usa banker's rounding e devolve
2,67 para 2,675, o que nao e o esperado em valor financeiro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

CENTAVOS = Decimal("0.01")


class ErroCalculo(Exception):
    """Dado ausente ou invalido impede o calculo.

    Existe para que a falha nunca vire zero: zero e um valor financeiro
    legitimo e mascararia o problema no total.
    """


@dataclass
class Memoria:
    """O rastro do calculo: o que foi consultado e como foi aplicado.

    Vai para o log e para a planilha. Sem isso, um numero fechado nao se
    explica nem se audita.
    """

    regra: str
    valor: Decimal
    parcelas: list[tuple[str, Decimal]] = field(default_factory=list)

    def descrever(self) -> str:
        if not self.parcelas:
            return self.regra
        detalhe = " + ".join(f"{rot}={val}" for rot, val in self.parcelas)
        return f"{self.regra} [{detalhe}]"


def _decimal(valor, campo: str) -> Decimal:
    """Converte para Decimal recusando ausencia e lixo.

    Passa por str de proposito: Decimal(float) arrastaria o erro binario do
    float para dentro do calculo.
    """
    if valor is None:
        raise ErroCalculo(f"{campo} ausente")
    try:
        return Decimal(str(valor))
    except Exception:
        raise ErroCalculo(f"{campo} nao numerico: {valor!r}") from None


def _quantidade(valor, campo: str = "quantidade") -> Decimal:
    quantidade = _decimal(valor, campo)
    if quantidade < 0:
        raise ErroCalculo(f"{campo} negativa: {quantidade}")
    return quantidade


def arredondar(valor: Decimal) -> Decimal:
    """Duas casas, ROUND_HALF_UP. Chamado uma unica vez, no fim."""
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_sic(quantidade, limite, valor_ate_limite, tarifa_excedente) -> Memoria:
    """Preco SIC: valor fixo dentro do limite, progressivo acima dele.

        quantidade <= limite:  valor_ate_limite
        quantidade  > limite:  valor_ate_limite + excedente x tarifa_excedente

    Progressivo: o volume dentro do limite nunca e cobrado por evento, ja
    esta pago pelo valor fixo.

    A tarifa do excedente so e exigida quando ha excedente - cobra-la antes
    recusaria registro que nao precisa dela.
    """
    qtd = _quantidade(quantidade)
    lim = _decimal(limite, "limite SIC")
    fixo = _decimal(valor_ate_limite, "valor SIC ate o limite")

    if qtd <= lim:
        return Memoria(
            regra=f"SIC ate o limite ({lim:,.0f})",
            valor=arredondar(fixo),
            parcelas=[("fixo", fixo)],
        )

    tarifa = _decimal(tarifa_excedente, "tarifa de eventos nao financeiros")
    excedente = qtd - lim
    variavel = excedente * tarifa
    return Memoria(
        regra=f"SIC progressivo: fixo + {excedente:,.0f} x {tarifa}",
        valor=arredondar(fixo + variavel),
        parcelas=[("fixo", fixo), ("excedente", variavel)],
    )


def calcular_fixo(valor_fixo, ativo: bool, emissor: str, servico: str) -> Memoria:
    """Valor fixo do emissor, devido inteiro.

    Nao multiplica pela quantidade: o valor e uma assinatura, nao um preco
    unitario. Servico inativo e erro distinto de servico ausente - um foi
    desligado, o outro nunca foi cadastrado.
    """
    if not ativo:
        raise ErroCalculo(f"servico fixo inativo: {emissor} / {servico}")

    valor = _decimal(valor_fixo, f"valor fixo de {emissor} / {servico}")
    if valor < 0:
        raise ErroCalculo(f"valor fixo negativo: {valor}")

    return Memoria(
        regra="FIXO por emissor (nao multiplica pela quantidade)",
        valor=arredondar(valor),
        parcelas=[("fixo", valor)],
    )


def calcular_variavel(quantidade, limite, tarifa_inicial, tarifa_final) -> Memoria:
    """Preco variavel, progressivo por faixa.

        quantidade <= limite:  quantidade x tarifa_inicial
        quantidade  > limite:  limite x tarifa_inicial
                               + (quantidade - limite) x tarifa_final

    Progressivo: passar do limite nao rebarata o volume ja consumido - so o
    excedente sai pela tarifa final.
    """
    qtd = _quantidade(quantidade)
    lim = _decimal(limite, "limite variavel")
    t_ini = _decimal(tarifa_inicial, "tarifa inicial")

    if qtd <= lim:
        valor = qtd * t_ini
        return Memoria(
            regra=f"VARIAVEL ate o limite: {qtd:,.0f} x {t_ini}",
            valor=arredondar(valor),
            parcelas=[("faixa inicial", valor)],
        )

    t_fim = _decimal(tarifa_final, "tarifa final")
    primeira = lim * t_ini
    excedente = qtd - lim
    segunda = excedente * t_fim
    return Memoria(
        regra=(
            f"VARIAVEL progressivo: {lim:,.0f} x {t_ini} + "
            f"{excedente:,.0f} x {t_fim}"
        ),
        valor=arredondar(primeira + segunda),
        parcelas=[("faixa inicial", primeira), ("excedente", segunda)],
    )
