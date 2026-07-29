# ddcapture

Captura, via API do Datadog, **quais widgets existem** num dashboard e **os valores
dentro deles** — identificando cada número pelo nome e atribuindo uma **categoria
automática**, sem catálogo mantido à mão.

O ponto que define o desenho: `GET /api/v1/dashboard/{id}` devolve **só a definição**
dos widgets — títulos, layout e as queries. Nenhum valor. Por isso o pipeline tem duas
fases: extrair as queries de cada widget e depois executá-las nas APIs de dados.

**Somente leitura.** Nada é criado, alterado ou apagado no Datadog — e isso é garantido
no código, não só na intenção.

---

## Instalação

Duplo clique em `instalar.bat`, ou pelo terminal:

```bat
instalar.bat              :: instala (reaproveita o .venv se já existir)
instalar.bat --recriar    :: apaga o .venv e refaz do zero
```

Em 5 passos: acha o Python, cria o `.venv`, instala as dependências, prepara o `.env`
e roda os testes.

**É idempotente e nunca sobrescreve o `.env`.** Se as chaves já estiverem preenchidas,
termina validando-as contra a API; se não, explica o que preencher e para por aí.

Cada falha tem sua mensagem e o comando para investigar:

| Situação | O que o instalador faz |
|---|---|
| Python ausente ou < 3.10 | Aponta o link de download; barra antes de estourar `SyntaxError` no primeiro uso |
| Falha de rede no PyPI | Diz que normalmente é proxy/firewall e mostra o comando sem `--quiet` |
| Testes falhando | Avisa que a instalação ficou inconsistente e mostra como ver o detalhe |
| Chaves rejeitadas | Separa "dependências ok, credenciais erradas" de "instalação quebrada" |

### Credenciais

| Variável | Onde obter |
|---|---|
| `DD_API_KEY` | Organization Settings → API Keys |
| `DD_APP_KEY` | Organization Settings → Application Keys (escopo `dashboards_read`) |
| `DD_SITE` | `datadoghq.com`, `datadoghq.eu`, `us3.datadoghq.com`, … |

A application key precisa também dos escopos das fontes consultadas
(`timeseries_query`, `logs_read_data`, `slos_read`, `monitors_read`).

Confirme com `ddcapture.bat --validar`: ele testa as chaves separadamente —
`GET /api/v1/validate` cobre só a API key e `GET /api/v1/dashboard` exige as duas,
então dá para saber **qual** das duas está errada.

> O `.env.example` é o template versionado. Nunca coloque chaves reais nele — o
> `.gitignore` cobre `.env`, não o `.example`.

---

## Uso

```bat
:: 1. as credenciais funcionam?
ddcapture.bat --validar

:: 2. achar o dashboard pelo título
ddcapture.bat --buscar "nome do painel"

:: 3. inventário de widgets e queries, sem consultar dados nem gastar rate limit
ddcapture.bat --dashboard-id abc-def-ghi --dry-run

:: 4. captura completa
ddcapture.bat --dashboard-id abc-def-ghi --from 01/07 --to 31/07

:: fixando template variables do dashboard
ddcapture.bat --dashboard-id abc-def-ghi --var env=prod --var service=checkout

:: inspecionar um JSON de dashboard salvo, sem credenciais
ddcapture.bat --arquivo dashboard.json --dry-run
```

### Janela de tempo

| Forma | Exemplos |
|---|---|
| Relativo | `-15m`, `15m`, `-1h`, `-7d` (o `-` é opcional) |
| Data BR | `01/07`, `01/07/2026`, `01/07/26`, `"01/07 08:30"` |
| Data ISO | `2026-07-01`, `"2026-07-01 08:30"` |
| Agora | `now` |
| Epoch | `1700000000` (s) ou `1700000000000` (ms, como vem da URL do Datadog) |

Três coisas que valem saber:

- **É dia/mês**, não mês/dia. `01/07` é 1º de julho.
- **Ano omitido = ano corrente.**
- **Data sem hora no `--to` cobre o dia inteiro** (23:59:59). Sem isso, `--to 31/07`
  pararia na virada da meia-noite e o dia 31 ficaria de fora.

Datas são lidas no **fuso local**. Antes de consultar, o coletor imprime a janela
resolvida para conferência:

```
Janela: 01/07/2026 00:00:00  ate  31/07/2026 23:59:59   (31.0 dias)
```

### O que o .bat faz

| Situação | Comportamento |
|---|---|
| **Sem argumentos** | Mostra os comandos mais usados e pausa — é o caso do duplo clique pelo Explorer, que senão fecharia a janela antes de dar para ler |
| **Com argumentos** | Repassa para `main.py` e **propaga o código de saída**, então serve para Agendador de Tarefas e scripts |
| **`.venv` ou `.env` faltando** | Para com a instrução do que fazer, em vez de um traceback de import |
| **Sempre** | Faz `cd` para a pasta do projeto e liga o codepage UTF-8 |

A pausa acontece **só** sem argumentos — é o que permite agendar:

```bat
schtasks /create /tn "Captura diaria" /sc daily /st 07:00 ^
  /tr "\"C:\caminho\para\ddcapture.bat\" --dashboard-id abc-def-ghi --from -1d"
```

---

## Somente leitura

`client._garantir_leitura` roda **antes** de cada requisição sair e só deixa passar
`GET` e os `POST` dos endpoints de consulta (`/api/v2/query/scalar`, `/timeseries`,
`/logs/analytics/aggregate` — esses leem dados; o corpo carrega a query, que não caberia
numa querystring).

Qualquer `PUT`, `PATCH`, `DELETE` ou `POST` fora dessa lista levanta
`ErroEscritaBloqueada` sem abrir conexão.

---

## Como funciona

### Fase 1 — descobrir os widgets

`GET /api/v1/dashboard/{id}` e achatamento recursivo da árvore. Widgets do tipo `group`
guardam os filhos em `definition.widgets`; o título do grupo acompanha cada filho e vira
a categoria da camada 1. Widgets sem dado (`note`, `image`, `free_text`) entram no
inventário marcados, e são pulados na fase 2.

### Fase 2 — executar as queries

Dois formatos convivem no mesmo dashboard:

```
moderno  requests[].queries[] + requests[].formulas[]  ->  /api/v2/query/{scalar,timeseries}
legado   requests[].q (string única)                   ->  GET /api/v1/query
```

Roteamento por `data_source`: `metrics`/`cloud_cost` → API de métricas; `logs`/`rum`/
`spans`/`events` → API de eventos; widgets de SLO → `/api/v1/slo/{id}/history`; widgets
de monitor → `/api/v1/monitor`.

### Fase 3 — categorização

Cascata; a primeira camada que resolve vence, e a coluna `categoria_origem` registra
qual foi:

| # | Camada | De onde vem | Origem |
|---|---|---|---|
| 1 | Grupo do dashboard | título do widget `group` que contém o widget | `grupo` |
| 2 | Palavra-chave | regex de `config/categorias.yaml` contra o **título do widget** | `palavra-chave` |
| 3 | Namespace | prefixo da métrica (`aws.rds.*` → Banco de Dados) | `namespace` |
| 4 | Fallback | `sem-categoria` | `fallback` |

A camada 2 olha só o título — usar o nome do valor deixaria uma tag como `host:web-01`
decidir a categoria.

**Tags** (`env`, `service`, `team`) não competem na cascata: são dimensões ortogonais,
extraídas do escopo da query e do grupo da série, e viram colunas próprias.

Para ajustar, edite `config/categorias.yaml` — as regras são avaliadas em ordem, e os
namespaces do prefixo mais longo para o mais curto.

### Como o valor é nomeado

`nome_valor` compõe `título do widget | série - escopo`:

```
CPU por host | CPU % - host:web-01
Erros 5xx por servico | Erros 5xx - service:checkout
Total de pedidos                       (fórmula sem alias: só o título)
```

O escopo entra porque um widget quebrado por tag produz vários números — sem ele não dá
para dizer qual valor é de quem.

A parte "série" é descartada quando não é um rótulo humano. Quando a fórmula do widget
não tem `alias`, a API devolve a própria expressão (`default_zero(query1)`) como nome da
coluna; isso não identifica nada, e o rótulo útil passa a ser o título do widget. A
checagem é exata — compara com as fórmulas e nomes de query do próprio widget, sem
heurística de texto.

---

## Saídas (`out/`)

A saída padrão é **um único `.xlsx`**, com **uma aba por categoria** e duas colunas —
o nome do campo e o valor, nada mais:

| Campo | Valor |
|---|---|
| Total de pedidos | 9315 |
| Pedidos aprovados | 3157 |
| Pedidos recusados | 3068 |

Os valores são gravados como **número**, não texto — o Excel soma direto.

### Vazio vira 0, erro fica em branco

Há duas razões diferentes para um campo não ter número, e elas não são a mesma coisa:

| Situação | Célula | Por quê |
|---|---|---|
| A query rodou e **não achou ocorrências** na janela | `0` | Zero é a resposta certa — não houve o evento |
| A API **recusou** a query (400/403) | *vazia* | O valor é desconhecido; um 0 aqui seria invenção |

A distinção fica na coluna `sem_dados` do CSV/JSON, e o resumo separa as contagens:

```
Widgets: 152 | Queries: 145 | Valores: 206 | Falhas: 2
  (2 campo(s) sem ocorrencias na janela, preenchidos com 0)
```

### Outros formatos

Desligados por padrão, ligáveis em `config/settings.yaml`:

| Sink | Conteúdo |
|---|---|
| `json` | hierárquico, com query, fonte, tags e timestamp de cada valor — para auditar de onde veio o número |
| `csv` | uma linha por valor com todas as colunas de metadado; `;` e BOM (abre certo no Excel pt-BR) |
| `xlsx_por_widget` | um arquivo **por widget** numa subpasta, + `_indice.xlsx` |
| `sqlite` | acumula um snapshot por execução; a view `historico` mostra a evolução de um mesmo valor no tempo |

No modo por widget, o `widget_id` entra sempre no nome do arquivo — é comum um dashboard
ter vários widgets com título idêntico, e sem o id um sobrescreveria o outro em silêncio.
O `_indice.xlsx` mapeia arquivo → widget → **query completa**, que é o que de fato os
distingue.

---

## Estrutura

```
instalar.bat      prepara o ambiente do zero (5 passos, idempotente)
ddcapture.bat     roda o coletor usando o Python do .venv
main.py           ponto de entrada; põe src/ no path

src/ddcapture/
  cli.py          argumentos, --dry-run, relatório
  config.py       .env + YAML, janelas de tempo
  client.py       HTTP, autenticação, retry, rate limit e o guarda somente-leitura
  dashboard.py    fase 1: busca e achata a árvore de widgets
  extractor.py    fase 2a: widget → QuerySpec (formatos moderno e legado)
  resolvers/      fase 2b: metrics | logs | slo | monitors
  categorize.py   fase 3: cascata de 4 camadas
  runner.py       orquestração
  sinks/          fase 4: excel (padrão) | json | csv | excel_widget | db
```

---

## Detalhes que costumam morder

- **Unidades de tempo**: `/api/v2/query/*` usa epoch em **milissegundos** no corpo;
  `/api/v1/query` usa **segundos** na querystring.
- **Template variables**: queries trazem `$env`, `$service`. São substituídas pelos
  defaults do dashboard antes de executar; sem isso a query falha. Uma variável não
  resolvida vira `*`.
- **`aggregator`**: obrigatório em query escalar de métrica, **rejeitado** em timeseries.
  Widgets `query_value` usam `last` (o painel mostra o último ponto), os demais usam o
  `agregador_padrao`.
- **`query_table`**: guarda `compute` e `group_by` **fora** da query — em
  `columns[].compute` e `rows.group_by[]`. Enviar a query como está faz a API responder
  `Error decoding payload`.
- **`data_source: dataset`**: widgets alimentados por célula de notebook não são
  alcançáveis por nenhuma API de query. Aparecem como falha, e é esperado.
- **Falha isolada**: uma query que falha não derruba a execução — vira uma linha com
  valor vazio e a mensagem na coluna `erro`, e o resumo lista o que falhou.
- **Rate limit**: 429 é tratado respeitando `X-RateLimit-Reset`, com backoff exponencial.

---

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

133 testes, **sem rede**: achatamento de grupos aninhados, os dois formatos de query,
`query_table`, substituição de template variables, as quatro camadas de categorização,
a leitura das respostas de cada API, o guarda somente-leitura, as janelas de tempo e
todos os formatos de saída — contra `tests/fixtures/dashboard_sample.json`.

## Requisitos

Python 3.10+ · `requests` · `PyYAML` · `openpyxl` · `python-dotenv` · `pytest`
