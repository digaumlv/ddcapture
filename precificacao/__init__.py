"""Precificacao dos servicos capturados do dashboard.

Tres responsabilidades separadas, nesta ordem de dependencia:

    captura      le o que o ddcapture ja produziu (nao captura nada)
    repositorio  consulta tarifas, limites e valores fixos na fonte de dados
    calculo      aplica as regras sobre numeros ja consultados

`calculo` nao conhece banco nem Datadog: recebe Decimal e devolve Decimal.
E o que permite testar as regras sem rede e sem banco.
"""

__version__ = "1.0.0"
