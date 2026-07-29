"""Cliente HTTP do Datadog: autenticacao, retry e tratamento de rate limit."""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

from .config import Credenciais

log = logging.getLogger(__name__)

# Status que compensa repetir. 429 tem tratamento proprio via X-RateLimit-Reset.
_RETENTAVEIS = frozenset({429, 500, 502, 503, 504})

# O coletor e estritamente somente-leitura: nada no Datadog pode ser criado,
# alterado ou apagado por ele. GET e sempre leitura; POST so e permitido nos
# endpoints de consulta abaixo, que apenas LEEM dados apesar do verbo (o corpo
# carrega a query, que nao caberia numa querystring).
_POST_SOMENTE_LEITURA = frozenset(
    {
        "/api/v2/query/scalar",
        "/api/v2/query/timeseries",
        "/api/v2/logs/analytics/aggregate",
        "/api/v2/spans/analytics/aggregate",
        "/api/v2/rum/analytics/aggregate",
        "/api/v2/events/analytics/aggregate",
    }
)


class ErroApi(Exception):
    """Falha em uma chamada a API do Datadog."""

    def __init__(self, mensagem: str, status: int | None = None, corpo: str = ""):
        super().__init__(mensagem)
        self.status = status
        self.corpo = corpo


class ErroEscritaBloqueada(ErroApi):
    """Uma chamada que modificaria o Datadog foi barrada antes de sair."""


class DatadogClient:
    def __init__(
        self,
        credenciais: Credenciais,
        *,
        timeout_s: int = 30,
        max_tentativas: int = 5,
        backoff_base_s: float = 1.0,
        sessao: requests.Session | None = None,
    ):
        self.credenciais = credenciais
        self.timeout_s = timeout_s
        self.max_tentativas = max_tentativas
        self.backoff_base_s = backoff_base_s
        self.sessao = sessao or requests.Session()
        self.sessao.headers.update(
            {
                "DD-API-KEY": credenciais.api_key,
                "DD-APPLICATION-KEY": credenciais.app_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def get(self, caminho: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._requisitar("GET", caminho, params=params)

    def validar_api_key(self) -> bool:
        """GET /api/v1/validate - checa SO a API key.

        Nao usa o _requisitar porque um 403 aqui e uma resposta valida
        ('chave invalida'), nao um erro de escopo a ser relatado.
        """
        resposta = self.sessao.get(
            f"{self.credenciais.base_url}/api/v1/validate",
            headers={"DD-API-KEY": self.credenciais.api_key},
            timeout=self.timeout_s,
        )
        if resposta.status_code == 403:
            return False
        if resposta.status_code >= 400:
            raise ErroApi(
                f"{resposta.status_code} ao validar a API key: {resposta.text[:300]}",
                resposta.status_code,
            )
        return bool(self._json(resposta).get("valid"))

    def validar_app_key(self) -> tuple[bool, str]:
        """Valida a application key com um endpoint que exige as duas chaves.

        Devolve (valida, detalhe). Um 403 aqui distingue 'chave invalida' de
        'chave valida sem o escopo dashboards_read' pela mensagem da API.
        """
        resposta = self.sessao.get(
            f"{self.credenciais.base_url}/api/v1/dashboard",
            timeout=self.timeout_s,
        )
        if resposta.status_code < 400:
            total = len(self._json(resposta).get("dashboards") or [])
            return True, f"acesso a dashboards confirmado ({total} dashboard(s) visiveis)"
        if resposta.status_code in (401, 403):
            return False, f"{resposta.status_code}: {resposta.text[:300]}"
        raise ErroApi(
            f"{resposta.status_code} ao validar a application key: {resposta.text[:300]}",
            resposta.status_code,
        )

    def post(self, caminho: str, corpo: dict[str, Any]) -> dict[str, Any]:
        return self._requisitar("POST", caminho, json=corpo)

    @staticmethod
    def _garantir_leitura(metodo: str, caminho: str) -> None:
        """Barra qualquer chamada que possa modificar o Datadog.

        A checagem acontece antes da requisicao sair, entao um erro de
        programacao vira excecao local em vez de uma escrita na plataforma.
        """
        if metodo == "GET":
            return
        if metodo == "POST" and caminho in _POST_SOMENTE_LEITURA:
            return
        raise ErroEscritaBloqueada(
            f"{metodo} {caminho} foi bloqueado: este coletor e somente-leitura "
            "e nao altera nada no Datadog."
        )

    def _requisitar(self, metodo: str, caminho: str, **kwargs: Any) -> dict[str, Any]:
        self._garantir_leitura(metodo, caminho)

        url = f"{self.credenciais.base_url}{caminho}"
        ultimo_erro: Exception | None = None

        for tentativa in range(1, self.max_tentativas + 1):
            try:
                resposta = self.sessao.request(
                    metodo, url, timeout=self.timeout_s, **kwargs
                )
            except requests.RequestException as exc:
                ultimo_erro = ErroApi(f"Falha de rede em {metodo} {caminho}: {exc}")
                if tentativa == self.max_tentativas:
                    break
                time.sleep(self._espera(tentativa))
                continue

            if resposta.status_code < 400:
                return self._json(resposta)

            corpo = resposta.text[:1000]

            if resposta.status_code == 401:
                raise ErroApi(
                    "401 - credenciais rejeitadas. Confira DD_API_KEY, DD_APP_KEY e DD_SITE "
                    "(uma chave criada em outro site nao funciona neste).",
                    401,
                    corpo,
                )
            if resposta.status_code == 403:
                raise ErroApi(
                    "403 - a application key nao tem escopo suficiente "
                    "(dashboards_read e os escopos de dados que voce consulta).",
                    403,
                    corpo,
                )

            if resposta.status_code not in _RETENTAVEIS or tentativa == self.max_tentativas:
                raise ErroApi(
                    f"{resposta.status_code} em {metodo} {caminho}: {corpo}",
                    resposta.status_code,
                    corpo,
                )

            espera = self._espera(tentativa, resposta)
            log.warning(
                "%s em %s - tentativa %d/%d, aguardando %.1fs",
                resposta.status_code,
                caminho,
                tentativa,
                self.max_tentativas,
                espera,
            )
            time.sleep(espera)

        raise ultimo_erro or ErroApi(f"Falha em {metodo} {caminho} apos {self.max_tentativas} tentativas")

    def _espera(self, tentativa: int, resposta: requests.Response | None = None) -> float:
        """Backoff exponencial com jitter, respeitando X-RateLimit-Reset em 429."""
        if resposta is not None and resposta.status_code == 429:
            reset = resposta.headers.get("X-RateLimit-Reset") or resposta.headers.get(
                "Retry-After"
            )
            if reset:
                try:
                    # O header vem em segundos ate a janela reabrir.
                    return min(float(reset) + 0.5, 120.0)
                except ValueError:
                    pass
        return min(self.backoff_base_s * (2 ** (tentativa - 1)), 60.0) + random.uniform(0, 0.5)

    @staticmethod
    def _json(resposta: requests.Response) -> dict[str, Any]:
        try:
            dados = resposta.json()
        except ValueError as exc:
            raise ErroApi(f"Resposta nao e JSON valido: {exc}", resposta.status_code) from exc
        if not isinstance(dados, dict):
            return {"data": dados}
        return dados
