# Arquitetura do TraceFlow

O TraceFlow é uma plataforma SaaS de observabilidade (o produto está descrito em [BRIEF.md](BRIEF.md)). Ele faz cinco coisas com o que chega:

1. Recebe spans no formato OTLP (OpenTelemetry), separados por projeto e ambiente.
2. Guarda cada trace para consulta.
3. Calcula as métricas de cada serviço a cada segundo.
4. Monta o mapa de dependências a partir dos próprios spans.
5. Avalia as regras de incidente de cada projeto. Quando um serviço adoece, cruza a saúde de cada nó com o mapa para apontar a causa provável, o raio de impacto e a severidade.

## Visão geral

```mermaid
flowchart LR
  subgraph demo["Loja de demonstração (projeto demo)"]
    LG[gerador de carga] --> GW[gateway]
    GW --> OR[orders]
    GW --> IN[inventory]
    OR --> IN
    OR --> PA[payments]
    OR --> NO[notifications]
    PA --> BK{{bank - externo, sem instrumentação}}
  end

  demo -- "OTLP/HTTP :4318 + chave do projeto" --> ING[Ingestão - FastAPI]
  ING -- XADD --> ST[(Redis Stream)]
  ST -- XREADGROUP --> PR[Processador - asyncio]
  PR -- INSERT --> DB[(PostgreSQL + TimescaleDB)]
  PR -- "PUBLISH 1x/s" --> PS[(Redis Pub/Sub)]
  PS --> API[API - FastAPI]
  DB --> API
  API -- "REST + WebSocket" --> WEB[Front - Next.js]
  API -. "playground: caos e tráfego (Redis)" .-> demo
```

O caminho de escrita (ingestão, stream e processador) e o caminho de leitura (API e front) não se tocam: o que eles compartilham é o banco, o snapshot ao vivo e o canal de Pub/Sub. Se a API cair, os dados continuam chegando. Se o banco ficar lento, o stream segura os dados até o processador conseguir gravar.

## Componentes

| Componente | Tecnologia | Responsabilidade | Porta |
|---|---|---|---|
| Loja de demonstração | FastAPI + SDK OpenTelemetry | Cinco serviços que geram traces reais e aceitam falhas injetadas | gateway em 8100 |
| Gerador de carga | Python (httpx, asyncio) | Tráfego contínuo, com ritmo controlado pelo playground | – |
| Ingestão | FastAPI | Valida a chave do projeto, recebe OTLP/HTTP (protobuf ou JSON) e põe no stream | 4318 |
| Fila | Redis Stream | Desacopla quem recebe de quem processa e segura picos | 6379 |
| Processador | Python asyncio | Persiste spans, agrega métricas ao vivo, monta o mapa, avalia regras, saúde e impacto | – |
| Banco | PostgreSQL 17 + TimescaleDB 2.30 | Spans e estatísticas (TimescaleDB). Usuários, projetos, chaves, regras e incidentes (tabelas comuns) | 5432 |
| API | FastAPI + SQLAlchemy | Autenticação, projetos, consultas, regras, playground, estado ao vivo por WebSocket | 8000 |
| Front | Next.js + React + TypeScript + Tailwind + shadcn/ui | Todas as telas, com o design system do brief | 3000 |

Ingestão, processador e API são um único pacote Python (`traceflow`) com três pontos de entrada. Uma imagem Docker, três comandos.

## Produto: usuários, projetos, ambientes e chaves

- **Usuário:** e-mail e senha (hash argon2). O login devolve um JWT de curta duração num cookie `httpOnly`, que o JavaScript da página não consegue ler. Isso protege o token de roubo por XSS.
- **Projeto:** pertence a um usuário e agrupa os serviços de uma aplicação. Tudo o que o TraceFlow guarda tem `project_id`.
- **Ambiente:** vem do atributo de recurso padrão `deployment.environment.name` (por exemplo `production`, `staging`, `demo`). Todas as telas filtram por ambiente.
- **Chave de API (ingestão):**
  - Cada projeto gera chaves no formato `tf_<prefixo>_<segredo>`.
  - A chave inteira aparece **uma vez**, na criação. O banco guarda só o prefixo (para identificar) e o SHA-256 do segredo. Como o segredo é longo e aleatório, um hash rápido é seguro; senhas de usuário, que são fracas, precisam de um hash lento (argon2).
  - As aplicações enviam a chave pelo cabeçalho `Authorization`, configurado com a variável padrão `OTEL_EXPORTER_OTLP_HEADERS`.
  - A ingestão guarda o resultado da validação (chave → projeto) em cache por 60 s, para não consultar o banco a cada requisição. Uma chave revogada para de funcionar em no máximo 60 s.
- **Projeto demo:** uma conta de visitante, só leitura, abre o projeto da loja de demonstração. É por ela que recrutadores usam a demonstração online, sem criar conta.

## O caminho de um span

1. O `gateway` recebe `POST /checkout`. A instrumentação do FastAPI abre um span `SERVER` e gera o `trace_id`.
2. Cada chamada HTTP de saída (httpx) abre um span `CLIENT` e envia o cabeçalho `traceparent` (W3C Trace Context). O serviço chamado continua o mesmo trace.
3. O `BatchSpanProcessor` de cada serviço junta os spans terminados e os envia a cada 500 ms para `POST /v1/traces`, com a chave do projeto.
4. A ingestão:
   - valida a chave (com cache);
   - valida o corpo e converte JSON para protobuf, se for o caso;
   - faz `XADD` de uma entrada por requisição no stream `traceflow:spans`, com o `project_id`.

   Se o stream passar do limite, ela responde `503` com `Retry-After`, e o exportador do OpenTelemetry tenta de novo depois.
5. O processador lê lotes com `XREADGROUP`, decodifica e grava no TimescaleDB com `ON CONFLICT DO NOTHING`. Só depois disso faz `XACK`.
6. Os mesmos spans alimentam as janelas ao vivo, o mapa de serviços e o índice de traces recentes, todos separados por projeto e ambiente.
7. A cada segundo o processador monta um snapshot por projeto e ambiente (métricas, mapa, saúde, incidente aberto), grava em `traceflow:snapshot:{projeto}:{ambiente}` e publica em `traceflow:live`.
8. A API repassa cada snapshot só aos WebSockets inscritos naquele projeto e ambiente. As telas de detalhe consultam o banco por REST.

Meta: o que acontece na loja aparece na tela em 2 a 4 segundos.

## Modelo de dados

### Span normalizado

| Campo | Origem no OTLP |
|---|---|
| `project_id` | a chave de API usada no envio |
| `environment` | atributo de recurso `deployment.environment.name` (padrão `default`) |
| `trace_id`, `span_id`, `parent_span_id` | ids do span, em hexadecimal |
| `service` | atributo de recurso `service.name` |
| `name`, `kind` | nome e tipo (`server`, `client`, `internal`, `producer`, `consumer`) |
| `start_time`, `duration_ms` | `start_time_unix_nano`, `end_time_unix_nano` |
| `status` | `unset`, `ok` ou `error` |
| `http_method`, `http_route`, `http_status_code` | `http.request.method`, `http.route`, `http.response.status_code` |
| `peer_address` | `server.address` + `server.port` (spans `CLIENT`) |
| `attributes` | demais atributos, em JSONB |

### Tabelas

**Telemetria** (escrita pelo processador com asyncpg, em lote):

- **`spans`**:
  - hypertable particionada por `start_time` em blocos de 1 hora, com retenção de 3 dias;
  - chave única `(trace_id, span_id, start_time)`, que torna a gravação idempotente;
  - índices em `trace_id`, em `(project_id, environment, service, start_time DESC)` e um índice parcial para spans raiz.
- **`edge_stats_1m`**: chamadas, erros e soma de duração por minuto e por aresta. Gravada com upsert que soma, então dados atrasados entram no minuto certo.

**Aplicação** (modelos SQLAlchemy, migrações com Alembic):

- **`users`**, **`projects`** e **`api_keys`** (prefixo, hash, criada em, revogada em).
- **`alert_rules`**: as regras de cada projeto (ver "Saúde e regras").
- **`incidents`** e **`incident_events`**:
  - o incidente: início, fim, severidade, causas prováveis, serviços e endpoints afetados;
  - os eventos: a linha do tempo (adoeceu, mudou a causa, recuperou), com a evidência em JSONB;
  - o resumo **antes / durante / depois** das métricas dos endpoints afetados.

Na primeira versão, as métricas históricas por serviço saem direto da tabela `spans` com `time_bucket` e `percentile_cont`. Se ficar lento, o próximo passo são continuous aggregates.

## Métricas ao vivo

- As métricas são **RED** (taxa, erros, duração), derivadas dos spans: as dos serviços vêm dos spans `SERVER`, as das arestas vêm dos spans `CLIENT`.
- A **disponibilidade** é a fração de requisições sem erro de servidor (sem 5xx) no período, por serviço e por endpoint de entrada.
- A agregação usa **o tempo do evento** (fim do span), em baldes de 1 segundo guardados por 60 segundos. O snapshot cobre os 10 segundos que terminam 3 segundos atrás. Esse atraso dá tempo para os lotes dos exportadores chegarem, e um span atrasado cai no balde certo.
- A duração é guardada num **histograma de baldes exponenciais** (fator 1,2, de 0,1 ms a 60 s, cerca de 73 baldes). O percentil sai da contagem acumulada, com erro relativo de no máximo 10%. Histogramas somam: janelas de 1 s viram 10 s ou 1 min sem perder nada, coisa que percentis prontos não permitem.

## Mapa de serviços

- **Nós** são serviços (`service.name`). **Arestas** são chamadas `CLIENT`, medidas do lado de quem chama, porque é quem sente a falha, inclusive quando o outro lado nem responde.
- **Quem é o chamado?** Um span `CLIENT` só sabe o endereço (`orders:8000`). O processador aprende o mapeamento endereço → serviço pareando cada `CLIENT` com o `SERVER` filho dele (`server.parent_span_id == client.span_id`).
- **Fora de ordem é o normal.** O `SERVER` termina antes do `CLIENT` que o chamou, e cada serviço envia em lotes no seu próprio ritmo. A primeira metade do par a chegar espera até 30 s numa "sala de espera" pelo `span_id` do cliente.
- **Nó virtual.** Um endereço que nunca pareia (API externa, serviço sem instrumentação) vira um nó virtual com o nome do endereço, como o `bank`. Um serviço conhecido que cai continua no mapa pelo nome aprendido: as chamadas até ele falham e ele não emite mais spans `SERVER`.

## Saúde, regras e análise de impacto

### Regras configuráveis

Cada projeto tem as suas regras, editáveis na tela. Uma regra é:

| Campo | Exemplo |
|---|---|
| alvo | um serviço, ou `*` para todos |
| métrica | `error_rate`, `p95_ms`, `p99_ms`, `rps`, `availability` |
| condição | `>= 0.05`, ou relativa à linha de base: `>= 2x baseline` |
| janela | 10 s, 1 min, 5 min |
| mínimo de requisições | 20 (com pouco tráfego, a regra não dispara) |
| estado resultante | `degradado` ou `falhando` |

Um projeto novo nasce com as regras padrão abaixo.

### Saúde de cada nó (avaliada por snapshot)

| Estado | Regra padrão |
|---|---|
| saudável | nenhuma regra disparada |
| degradado | erro ≥ 5% (com ≥ 20 requisições na janela) **ou** p95 ≥ 2× a linha de base e ≥ linha de base + 50 ms |
| falhando | erro ≥ 25% |
| sem resposta | chamadas para ele falham por conexão ou timeout e ele não emite spans `SERVER` (fixo, não é regra) |

- A **linha de base** é uma média móvel exponencial do p95, atualizada só enquanto o nó está saudável, para a falha não virar o novo normal.
- Há **histerese**: o estado só muda depois de 3 snapshots seguidos, para o mapa não piscar.
- Um nó virtual herda a saúde das arestas que chegam nele.

### Causa provável

1. Pegar o subgrafo dos nós não saudáveis.
2. Agrupar os ciclos em componentes fortemente conexos (Tarjan) e considerar cada grupo como um nó.
3. Os candidatos são os **sumidouros** desse subgrafo: nós doentes sem nenhuma dependência doente. Se o `payments` está lento porque o `bank` está lento, o candidato é o `bank`.
4. Cada candidato vem com evidência dos traces recentes:
   - **origem do erro**: o span com erro mais profundo, sem filhos com erro;
   - **tempo próprio**: a duração menos a dos filhos, comparado com a linha de base.

   Se a dependência doente não explica a piora de quem a chama, os dois aparecem como causa.

### Raio de impacto

- **Afetados**: ancestrais da causa no grafo (busca reversa) que estão doentes. **Em risco**: ancestrais ainda saudáveis.
- **Endpoints de entrada afetados**: o processador guarda, para os traces dos últimos 30 s, a rota de entrada e os serviços tocados. Assim ele diz, por exemplo, que `POST /checkout` passa pelo `payments` e está com 38% de erro, enquanto `GET /products` não passa e segue normal.

### Incidentes e severidade

Um incidente:
- **abre** quando um nó sai de saudável (depois da histerese);
- **é atualizado** a cada snapshot;
- **fecha** depois de 30 s com tudo saudável.

A severidade sai do impacto **em quem usa**, não do serviço que quebrou:

| Severidade | Quando |
|---|---|
| **SEV1** crítico | um endpoint de entrada com erro ≥ 25% ou sem resposta |
| **SEV2** alto | um endpoint de entrada com erro ≥ 5% ou p95 ≥ 2× a linha de base |
| **SEV3** baixo | uma dependência doente sem efeito nos endpoints de entrada (por exemplo, o `notifications` caído: as compras seguem) |

O incidente guarda a linha do tempo dos eventos e, ao fechar, o resumo **antes / durante / depois** de cada endpoint afetado: taxa, erro e p95 nos 5 minutos antes, no pior minuto e nos 5 minutos depois da recuperação.

## Incident Playground (projeto demo)

- **Cenários prontos**, cada um combinando falhas no Redis da loja:

  | Cenário | Falha injetada |
  |---|---|
  | Banco lento | +1500 ms no `bank` |
  | Pagamentos instáveis | 30% de erro no `payments` |
  | E-mail fora do ar | `notifications` down |
  | Estoque fora do ar | `inventory` down |

  Também dá para montar uma falha à mão, por serviço.
- **Tráfego:** o ritmo do gerador de carga (req/s e fração de compras) é controlado pela tela.
- **Toda falha expira sozinha** (`EXPIRE` no hash do Redis, 5 minutos por padrão). Na demonstração pública, ninguém deixa a loja quebrada para o próximo visitante.
- **Uma falha por vez** na demonstração pública, com limite de taxa por visitante.
- **O final do ciclo:** o playground mostra o incidente sendo detectado, a causa provável e, depois da recuperação, a comparação antes / depois.

## O processador e o banco (Etapa 3)

- **Normalização** (`normalize.py`):
  - o que as telas consultam vira coluna, o resto vai para JSONB;
  - aceita os nomes novos e os antigos das convenções HTTP;
  - remove `\x00`, converte `NaN` em texto e corta textos acima de 8 KB;
  - descarta spans fora da janela de 3 dias atrás a 10 minutos à frente.
- **Gravação** (`storage.py`): COPY para uma tabela temporária, depois `INSERT ... ON CONFLICT DO NOTHING`, numa transação. Devolve quantas linhas eram novas.
- **Laço:**
  - ao subir, relê os próprios pendentes (`"0"`), depois lê lotes novos (`">"`, até 200);
  - grava, faz `XACK` e `XDEL`;
  - a cada 10 s, roda o `XAUTOCLAIM` (pendentes parados há mais de 30 s) e escreve as estatísticas no log.
- **Falhas:**
  - erro passageiro: espera crescente, sem confirmar;
  - dado recusado: o lote é dividido ao meio até isolar a linha;
  - lote ilegível: vai para `traceflow:spans:dead`;
  - erro inesperado: o processo cai e é reiniciado (D28).
- **Esquema:** migrações Alembic, aplicadas pelo contêiner `migrate`. A `0001` cria `projects` (com o `demo`), a hypertable `spans` (partições de 1 h), os índices e a retenção de 3 dias.
- **Medido:**
  - 101 spans/s em regime, com 42 ms de atraso médio;
  - uns 4.500 spans/s esvaziando uma fila acumulada;
  - totais aceitos e gravados iguais depois de `kill -9` no processador e de 5 min de banco fora.

## A ingestão (Etapa 2)

- `POST /v1/traces` aceita protobuf e JSON, com gzip opcional. A resposta de sucesso vai no mesmo formato da requisição.
- O corpo é lido em pedaços e recusado acima de 4 MB (`413`). O limite vale também depois de descomprimir, contra bombas de compressão.
- O OTLP/JSON traz os ids em hexadecimal, e não em base64 como o mapeamento padrão do protobuf. A ingestão converte antes de validar.
- Lote vazio responde `200` sem tocar na fila.
- Fila acima do limite ou Redis indisponível: `503` com `Retry-After`. O exportador do OpenTelemetry respeita o tempo pedido.
- Na fila: `project`, `received_at_ms`, `span_count` e `payload` (protobuf). O formato é definido em `traceflow/streams.py`, compartilhado com o processador.
- A cada 10 s, o log mostra spans/s aceitos, o tamanho da fila e as recusas por motivo.

## A loja de demonstração (Etapa 1)

- Um pacote (`demo/`, `shop`), uma imagem e um módulo por serviço. Cada contêiner sobe um módulo com uvicorn.
- A telemetria é configurada só pelas variáveis padrão do OpenTelemetry (`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_BSP_SCHEDULE_DELAY=500`, `OTEL_SEMCONV_STABILITY_OPT_IN=http`). Trocar o destino dos spans é só mudar o compose.
- Os spans internos `http send`/`http receive` da instrumentação ASGI ficam desligados. Uma compra gera 10 spans: 5 `SERVER` e 5 `CLIENT`.
- Toda chamada entre serviços tem timeout de 2 s. Falha de conexão vira 502, timeout vira 504, 5xx vira 502, e o 4xx volta para a rota decidir.
- O `notifications` é uma dependência **não crítica**: se falhar, o pedido sai com `notified=false` e a falha fica só no span `CLIENT`.
- O gerador de carga é de modelo aberto (ritmo fixo, sem esperar respostas), para não cair em *coordinated omission*. Por padrão manda 20 req/s, com 30% de compras e 2% de produtos inexistentes (404).
- As falhas ficam em duas camadas. O **"fora do ar"** fica por fora da instrumentação: responde 503 sem gerar span, como o balanceador na frente de um serviço caído. O **atraso e o erro** ficam por dentro e aparecem no span.

## API

| Método | Rota | Para quê |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login`, `/api/auth/logout` | conta e sessão (cookie `httpOnly`) |
| GET/POST/PATCH/DELETE | `/api/projects` | projetos do usuário |
| GET/POST/DELETE | `/api/projects/{id}/keys` | chaves de ingestão (a chave inteira só aparece na criação) |
| GET | `/api/projects/{id}/environments` | ambientes vistos nos spans |
| GET | `/api/projects/{id}/services` | serviços com as métricas atuais |
| GET | `/api/projects/{id}/services/{name}/metrics?env&from&to&step` | séries RED e disponibilidade |
| GET | `/api/projects/{id}/services/{name}/operations` | endpoints do serviço com RED de cada um |
| GET | `/api/projects/{id}/traces?env&service&operation&status&min_duration&from&to` | busca de traces (pelos spans raiz) |
| GET | `/api/projects/{id}/traces/{trace_id}` | todos os spans de um trace (waterfall) |
| GET | `/api/projects/{id}/map?env&from&to` | grafo de um intervalo passado |
| GET/POST/PATCH/DELETE | `/api/projects/{id}/rules` | regras de incidente |
| GET | `/api/projects/{id}/incidents`, `/api/projects/{id}/incidents/{iid}` | incidentes, linha do tempo e antes / depois |
| GET/POST/DELETE | `/api/playground/scenarios`, `/api/playground/faults`, `/api/playground/traffic` | cenários, falhas e tráfego (só projeto demo) |
| GET | `/api/pipeline` | saúde do próprio TraceFlow: spans/s, atraso do stream, pendentes |
| GET | `/metrics` | as mesmas métricas do pipeline, no formato do Prometheus |
| WS | `/api/live` | o cliente se inscreve num projeto, ambiente e tela; recebe o snapshot atual e um novo por segundo |

A documentação interativa da API sai sozinha do FastAPI, em `/docs`.

## Front

- **Pilha:**
  - Next.js (App Router) com React e TypeScript;
  - Tailwind CSS e shadcn/ui para o design system;
  - Recharts para os gráficos e React Flow para o mapa;
  - TanStack Query para as chamadas REST.
- **Design system:** tokens de cor e tipografia do brief: fundo `#0B1020`, superfícies em azul grafite, primária `#3B82F6`, verde saudável, vermelho crítico, Inter e JetBrains Mono. Ficam em variáveis CSS que o Tailwind e o shadcn/ui usam.
- **Telas:**
  - página inicial pública;
  - login;
  - projetos e chaves;
  - dashboard ao vivo;
  - serviço;
  - mapa;
  - traces e waterfall;
  - incidentes;
  - regras;
  - playground.
- As telas do produto são componentes de cliente (`"use client"`), porque vivem de dados ao vivo. A página inicial pública é renderizada no servidor, para carregar rápido e ser indexada.

## Qualidade e entrega

| Camada | Ferramenta | O que cobre |
|---|---|---|
| Python | pytest, ruff, mypy | algoritmos (histograma, pareamento, causa provável, regras), rotas, ingestão |
| Front, unidade | Vitest + Testing Library | componentes e formatação de dados |
| Ponta a ponta | Playwright | login, ver o dashboard, injetar uma falha no playground e ver o incidente abrir |
| Carga | gerador próprio | spans/s suportados e atraso do pipeline, com números no README |
| CI | GitHub Actions | tudo acima a cada push; imagens Docker construídas |
| Demonstração pública | front na Vercel, backend num serviço de contêineres | projeto demo aberto a visitantes, falhas com expiração (D24) |

## Estrutura do repositório

```
backend/                 pacote traceflow (ingest, processor, api, storage, migrations)
  src/traceflow/
  tests/
demo/                    loja de demonstração, middleware de caos, gerador de carga
web/                     front Next.js + TypeScript
docs/                    brief, arquitetura e decisões
docker-compose.yml
```

## Etapas

| Etapa | Entrega | Fase do brief |
|---|---|---|
| 0 ✓ | Arquitetura e decisões | Foundation |
| 1 ✓ | Loja de demonstração instrumentada, rodando no Docker Compose e conferida num Jaeger provisório | Telemetry |
| 2 ✓ | Ingestão OTLP → Redis Stream, com ambiente e projeto padrão | Telemetry |
| 3 ✓ | Processador → TimescaleDB, com idempotência e recuperação de pendentes; banco da aplicação com SQLAlchemy e Alembic | Telemetry |
| 4 | Autenticação, projetos, chaves de API e ambientes; a ingestão passa a exigir chave | Foundation |
| 5 | Front: Next.js, design system, login, projetos, busca de traces e waterfall | Foundation + Tracing |
| 6 | Dashboard ao vivo (histogramas, snapshot, WebSocket, disponibilidade) e a tela de serviço | Dashboard |
| 7 | Mapa de serviços (pareamento, nós virtuais) | Advanced |
| 8 | Incidentes: regras configuráveis, saúde, causa provável, raio de impacto, severidade, antes / depois | Tracing & Incidents |
| 9 | Incident Playground: cenários, controle de tráfego, falhas com expiração | Advanced |
| 10 | Produção: Vitest, Playwright, CI, teste de carga, `/metrics`, deploy da demonstração pública, README com GIF | Production & Portfolio |

O brief estima 12 semanas com dedicação parcial.

## Limites conhecidos

- **Um processador só.** Para escalar é preciso particionar o stream por `trace_id`, para que os spans de um trace caiam sempre no mesmo consumidor (o mesmo papel das partições do Kafka).
- **Sem amostragem.** A loja envia 100% dos traces.
- **Projetos com um dono só.** Não há times nem papéis (dono, membro, leitor). É o próximo passo natural do modelo de projetos.
- **Estado ao vivo em memória.** Ao reiniciar, o processador refaz as janelas em cerca de 10 s e reaprende o mapeamento de endereços.
- **A causa provável é uma heurística.** Ela mostra correlação, e por isso cada causa vem com a evidência e pode haver mais de uma.
- **Regras por limiar.** Não há detecção de anomalia estatística (sazonalidade, previsão).
