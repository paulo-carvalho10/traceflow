# Decisões

Cada decisão tem o que foi escolhido, o que ficou de fora e por quê. Quando uma decisão mudar, ela ganha uma nota de revisão em vez de ser apagada.

## D1. Receber dados no padrão OpenTelemetry (OTLP)

- **Escolha:** a ingestão fala OTLP/HTTP em `/v1/traces`, na porta padrão 4318.
- **Alternativa:** um SDK e um formato próprios.
- **Por quê:** qualquer aplicação já instrumentada com OpenTelemetry, em qualquer linguagem, manda dados para o TraceFlow sem mudar uma linha. Um formato próprio só funcionaria com a loja de demonstração.

## D2. Métricas derivadas dos spans

- **Escolha:** RED (taxa, erros, duração) calculado a partir dos spans `SERVER` e `CLIENT`.
- **Alternativa:** receber também métricas OTLP (CPU, memória, contadores).
- **Por quê:** um sinal só, um pipeline só. O Grafana Tempo e o Jaeger fazem o mesmo para gerar métricas de serviço.
- **Custo:** não há métricas de recurso, como CPU e memória.

## D3. Redis Stream entre a ingestão e o processamento

- **Escolha:** a ingestão só valida e enfileira. O processador consome com consumer group e ACK.
- **Alternativas:**
  - gravar direto no banco na requisição de ingestão;
  - Kafka;
  - RabbitMQ.
- **Por quê:**
  - Picos e lentidão do banco não chegam ao cliente.
  - Um span não se perde se o processador cair, porque fica pendente até o ACK.
  - O Redis já é necessário para o Pub/Sub e o caos.
  - O Kafka resolveria o mesmo problema em escala muito maior, mas custaria um cluster pesado num projeto que roda num notebook.

## D4. TimescaleDB para guardar spans

- **Escolha:** PostgreSQL 16 com a extensão TimescaleDB (hypertable por tempo, retenção automática).
- **Alternativas:**
  - ClickHouse;
  - Prometheus;
  - PostgreSQL puro.
- **Por quê:**
  - É SQL de Postgres, com particionamento por tempo e retenção prontos.
  - O ClickHouse é a escolha de ferramentas grandes (SigNoz, Uptrace) e é mais rápido em volume alto, mas exige outro dialeto e outra operação.
  - O Prometheus só guarda métricas, não traces.
  - O Postgres puro exigiria fazer o particionamento e a retenção à mão.

## D5. A ingestão valida, mas não normaliza

> Revisada na Etapa 2. A primeira versão dizia que a ingestão nem decodificava o protobuf.

- **Escolha:**
  - A ingestão decodifica cada lote só para validar e contar os spans.
  - Na fila vão os bytes protobuf originais, uma entrada por requisição.
  - Requisições em JSON são convertidas para protobuf antes.
- **Alternativas:**
  - Não decodificar nada.
  - Normalizar os spans já na ingestão.
- **Por quê:**
  - Sem decodificar, lixo entraria na fila e só seria descoberto pelo processador, longe de quem mandou. Assim a aplicação recebe `400` na hora.
  - Normalizar exigiria percorrer cada atributo e montar o formato interno, que é o trabalho pesado. Esse trabalho fica num lugar só, o processador.
  - Com o protobuf em C (`upb`), decodificar um lote de 4 KB custa microssegundos.
  - Uma entrada por requisição, e não por span, reduz as operações no Redis.

## D6. Um processador só, com caminho de escala definido

- **Escolha:** um processo consumidor.
- **Por quê:**
  - O pareamento CLIENT/SERVER e o índice de traces recentes precisam ver todos os spans de um trace.
  - Consumer groups do Redis distribuem as entradas sem critério de chave, então dois consumidores separariam spans do mesmo trace.
- **Para escalar:** N streams particionados por hash do `trace_id`, um consumidor por stream e agregados mesclados. É o mesmo princípio das partições do Kafka.

## D7. Histogramas exponenciais para percentis

- **Escolha:** baldes com fator 1,2 entre 0,1 ms e 60 s (cerca de 73 baldes), erro relativo de no máximo 10%.
- **Alternativas:**
  - guardar todas as durações e ordenar;
  - t-digest ou DDSketch.
- **Por quê:**
  - Memória fixa por janela.
  - Histogramas se somam, então janelas de 1 s viram 10 s ou 1 min sem perder precisão. Já a média de dois p95 não é o p95 de nada.
  - É simples de explicar e testar.
  - O DDSketch é a evolução natural se precisar de mais precisão.

## D8. Janela ao vivo por tempo do evento, com atraso de 3 s

- **Escolha:** baldes de 1 s pelo fim do span. O snapshot cobre `[agora − 13 s, agora − 3 s)`.
- **Alternativa:** agregar pelo momento em que o span chega.
- **Por quê:** os exportadores enviam em lotes. Por tempo de chegada, a taxa oscilaria com o ritmo dos lotes e não com o tráfego real. O atraso é o preço de números corretos.

## D9. Arestas medidas pelo lado de quem chama, com nós virtuais

- **Escolha:**
  - As arestas vêm dos spans `CLIENT`.
  - O pareamento com o `SERVER` filho só serve para aprender qual serviço atende cada endereço.
  - Endereços que nunca pareiam viram nós virtuais.
- **Alternativa:** só criar aresta quando os dois spans do par chegam.
- **Por quê:**
  - Quem chama sente a falha, mesmo quando o chamado está caído e não emite nada.
  - Esperar pelo par atrasaria o mapa e esconderia justamente o serviço que caiu.
  - O Grafana Tempo usa a mesma ideia de nó virtual.

## D10. Causa provável pelos sumidouros do subgrafo doente

- **Escolha:**
  - Os candidatos são os nós doentes sem dependências doentes, com ciclos agrupados por componentes fortemente conexos.
  - A evidência vem dos traces: a origem do erro e o tempo próprio.
- **Alternativa:** modelos estatísticos ou aprendizado de máquina.
- **Por quê:**
  - É explicável e determinística.
  - Funciona sem histórico longo.
  - Quando erra, a evidência mostra por quê.
- **Limite:** mostra correlação, não prova causa. Por isso pode apontar mais de uma causa.
- **Na implementação (Etapa 8):** a evidência dos traces é a origem do erro. A "piora emprestada" é medida comparando quanto o p95 de cada um subiu acima da linha de base; o tempo próprio ficou para depois. Também entra como causa quem está mais doente do que as dependências explicam.

## D11. Gravação idempotente (entrega pelo menos uma vez)

- **Escolha:** ACK só depois de gravar no banco, com chave única `(trace_id, span_id, start_time)` e `ON CONFLICT DO NOTHING`.
- **Por quê:**
  - Se o processador cair entre a gravação e o ACK, o lote é relido e regravado sem duplicar nada.
  - O `start_time` entra na chave porque o TimescaleDB exige a coluna de partição em índices únicos.

## D12. WebSocket para o estado ao vivo

- **Escolha:** um WebSocket por aba. A API mantém uma única assinatura no Redis e repassa a cada cliente.
- **Alternativas:**
  - polling a cada segundo;
  - Server-Sent Events.
- **Por quê:**
  - O polling desperdiça requisições e chega atrasado.
  - O SSE resolveria o envio do servidor.
  - O WebSocket também deixa o cliente dizer o que está olhando (por exemplo, um serviço) para receber só o detalhe daquela tela.

## D13. Front em Next.js + TypeScript + Tailwind + shadcn/ui

> Revisada em 19/10/2026, com a chegada do brief. A versão anterior previa Vite.

- **Escolha:**
  - Next.js (App Router), com Tailwind CSS e shadcn/ui no design system;
  - TanStack Query para as chamadas REST;
  - React Flow para o mapa;
  - Recharts para os gráficos.
- **Alternativa:** React com Vite, uma SPA pura servida por nginx.
- **Por quê:**
  - O brief pede Next.js, e ele é o framework React mais pedido em vagas Full Stack.
  - O produto agora tem uma página inicial pública e uma demonstração para recrutadores. Renderizar essa página no servidor faz ela carregar rápido e ser indexada.
  - As telas do produto continuam como componentes de cliente, porque vivem de dados ao vivo.
- **Custo:** o Next.js tem mais conceitos (servidor e cliente, roteamento por pastas) que uma SPA com Vite.

## D14. Um pacote Python, três processos

- **Escolha:** ingestão, processador e API num pacote só (`traceflow`), com uma imagem Docker e três comandos.
- **Por quê:**
  - Compartilham o modelo de span e o acesso ao banco.
  - Rodam separados porque têm cargas diferentes e uma falha num não derruba os outros.

## D15. Fora do escopo

> Revisada em 19/10/2026, com a chegada do brief. Login, projetos e ambientes entraram (D19).

- **Fora do escopo:**
  - logs;
  - alertas por e-mail ou Slack;
  - times e papéis dentro de um projeto;
  - amostragem de traces.
- **Por quê:** o diferencial do projeto é a propagação de falhas e a investigação de incidentes. Cada um desses itens é um projeto à parte, e ficam como próximos passos.

## D16. Spans internos da instrumentação ASGI desligados

- **Escolha:** `exclude_spans=["receive", "send"]` na instrumentação do FastAPI.
- **Por quê:**
  - Eram 14 dos 25 spans de uma compra, sem informação que o span `SERVER` já não tenha.
  - Desligá-los reduz em mais da metade o volume que a ingestão e o processador vão tratar.
  - Um teste garante que cada requisição gera um span só.

## D17. Falhas de dependência traduzidas em 502/504, com dependências não críticas

- **Escolha:**
  - Timeout de 2 s em toda chamada.
  - Falha de conexão e 5xx viram 502, timeout vira 504, e o 4xx é repassado.
  - O e-mail de confirmação não derruba a compra.
- **Por quê:**
  - É o comportamento que se espera de serviços reais, e gera a cadeia de erros que a análise de impacto vai precisar interpretar.
  - A dependência não crítica cria de propósito um caso em que uma aresta fica vermelha sem que quem chama adoeça.

## D18. Gerador de carga em modelo aberto

- **Escolha:** requisições num ritmo fixo, independente das respostas, com um limite de 500 pendentes.
- **Alternativa:** usuários em laço fechado (manda, espera, manda).
- **Por quê:** no modelo fechado, um sistema lento recebe menos carga e a lentidão some das medições (*coordinated omission*).

## D19. Usuários, projetos, ambientes e chaves de ingestão

- **Escolha:**
  - **Contas:** senha com hash argon2 e sessão em JWT num cookie `httpOnly`.
  - **Dados:** tudo separado por `project_id` e ambiente.
  - **Ambiente:** vem do atributo padrão `deployment.environment.name`.
  - **Chaves de ingestão:** formato `tf_<prefixo>_<segredo>`. O banco guarda só o prefixo e o SHA-256 do segredo. A chave inteira aparece uma vez, e a ingestão valida com cache de 60 s.
- **Alternativas:**
  - **Sem login.** Era o plano antes do brief.
  - **Guardar a chave em texto.**
  - **JWT no localStorage.**
- **Por quê:**
  - O brief pede um SaaS com projetos e ambientes, e separar dados por cliente é o que transforma uma ferramenta num produto.
  - **SHA-256 na chave e argon2 na senha:** a chave é longa e aleatória, então um hash rápido basta. A senha é escolhida por gente e precisa de um hash lento contra força bruta.
  - **O cookie `httpOnly`** não pode ser lido por JavaScript, o que protege a sessão de XSS.
  - **O cache na ingestão** evita uma consulta ao banco por requisição. O custo é a revogação levar até 60 s.
  - **As aplicações mandam a chave pela variável padrão** `OTEL_EXPORTER_OTLP_HEADERS`, sem código.

## D20. SQLAlchemy para a aplicação, asyncpg direto para a telemetria

- **Escolha:**
  - Usuários, projetos, chaves, regras e incidentes usam modelos SQLAlchemy 2 (assíncrono), com migrações Alembic.
  - A gravação de spans e as consultas de séries temporais usam SQL escrito à mão com asyncpg.
- **Alternativa:** SQLAlchemy em tudo, ou SQL à mão em tudo.
- **Por quê:**
  - O ORM brilha no CRUD: menos código repetido, validação de relações, migrações versionadas.
  - Na gravação de milhares de spans por segundo e nas consultas com `time_bucket` e `percentile_cont`, o ORM só atrapalha. Ali o SQL direto é mais rápido e mais claro.
  - Cada ferramenta fica onde é melhor.

## D21. Regras de incidente configuráveis e severidade pelo impacto

- **Escolha:**
  - Regras por projeto: alvo, métrica, condição absoluta ou relativa à linha de base, janela, mínimo de requisições e estado. Um projeto novo nasce com as regras padrão.
  - A severidade (SEV1 a SEV3) sai do efeito nos endpoints de entrada, não do serviço que quebrou.
- **Por quê:**
  - Cada aplicação tem o seu normal: 5% de erro é desastre num checkout e aceitável num serviço de recomendações.
  - A severidade pelo impacto responde o que importa: os clientes estão sentindo? O `notifications` caído é SEV3, porque as compras seguem.
- **Na implementação (Etapa 8):** a janela de toda regra é a do retrato (10 s); as janelas de 1 e 5 min ficaram para depois.

## D22. Incident Playground com falhas que expiram

- **Escolha:**
  - Cenários prontos e falhas manuais.
  - O ritmo do tráfego é controlado pela tela.
  - Toda falha tem `EXPIRE` no Redis (5 minutos por padrão).
  - Na demonstração pública: uma falha por vez e limite de taxa por visitante.
- **Por quê:** a demonstração é pública. Sem expiração, um visitante deixaria a loja quebrada para o próximo. Com ela, o sistema sempre volta sozinho ao normal, e a recuperação vira parte da demonstração (o "antes / depois" do incidente).

## D23. Pipeline próprio em vez de Prometheus + Grafana Tempo

- **Escolha:**
  - Ingestão, fila, processador e armazenamento próprios.
  - Do Prometheus fica só o formato de exposição: o TraceFlow publica as métricas do próprio pipeline em `/metrics`.
- **Alternativa (do brief):** guardar traces no Grafana Tempo e métricas no Prometheus, com o backend só consultando.
- **Por quê:**
  - Com Tempo e Prometheus, o TraceFlow viraria uma tela por cima de ferramentas prontas.
  - Montar o trace, calcular percentis, lidar com spans fora de ordem e montar o mapa seriam trabalho delas.
  - Essas são justamente as partes que mostram engenharia e que mais aparecem nas perguntas de entrevista.
- **O `/metrics` é o meio-termo:** o TraceFlow fala a língua do ecossistema, e qualquer Prometheus pode monitorar o próprio TraceFlow.

## D24. Demonstração pública: front na Vercel, backend num serviço de contêineres

> Revisada em 19/10/2026. O usuário escolheu a Vercel para a versão online.
>
> **Revista de novo na Etapa 10 (D69):** sem domínio próprio, tudo foi para um servidor só, atrás de um Caddy.

- **Escolha:**
  - O front em Next.js fica na **Vercel**.
  - O backend fica num serviço que roda **contêineres ligados o tempo todo**, com o mesmo Docker Compose. O backend é a ingestão, o processador, a API, o Redis, o TimescaleDB e a loja de demonstração. O provedor será escolhido na Etapa 10 (Fly.io, Railway, Render ou uma VPS).
- **Por que não tudo na Vercel:** a Vercel roda funções curtas, sob demanda, que terminam depois de cada resposta. Por isso ela não comporta:
  - o processador, que fica ligado consumindo a fila;
  - o Redis e o banco;
  - a loja e o gerador de carga;
  - conexões WebSocket abertas por minutos.
- **Consequências para o desenho:**
  - Front e API em domínios diferentes. O ideal é um domínio próprio com subdomínios (`app.` na Vercel e `api.` no backend), para o cookie de sessão continuar sendo do mesmo site.
  - O WebSocket conecta direto no backend, porque a Vercel não repassa WebSocket. Ele se autentica com um **ticket de uso único** pedido por REST logo antes de conectar.
  - A API precisa de CORS liberando só o domínio do front.
- **Por que é uma boa divisão:** a Vercel é feita para Next.js (CDN, deploy a cada push, prévia por pull request), e o backend continua idêntico ao do notebook.

## D25. O tamanho da fila é o que falta processar

> Na Etapa 10, o freio passou a ser a idade da fila (D65). O resto continua valendo.

- **Escolha:**
  - O processador apaga cada entrada depois de tratá-la (`XACK` + `XDEL`), então `XLEN` é exatamente o atraso do pipeline.
  - A ingestão lê o `XLEN` em segundo plano a cada 250 ms e recusa com `503` acima de `TRACEFLOW_MAX_BACKLOG` (50 mil lotes).
  - O `MAXLEN` aproximado de 2× esse valor é só um teto de segurança.
- **Alternativa:** guardar as entradas já processadas e aparar por `MAXLEN`.
- **Por quê:**
  - Com entradas processadas na fila, o `XLEN` ficaria perto do máximo o tempo todo e o freio dispararia sem motivo.
  - Pior: um `MAXLEN` agressivo poderia apagar lotes que ainda nem foram lidos.
  - Ler o tamanho em segundo plano evita uma ida a mais ao Redis por requisição. A fila não enche em 250 ms.

## D26. A ingestão desiste rápido e não se instrumenta

- **Escolha:**
  - O cliente do Redis tenta no máximo uma vez a mais, com espera de até 200 ms. O padrão do redis-py são três tentativas com espera crescente.
  - A ingestão não usa OpenTelemetry nela mesma: a saúde dela sai por contadores e pelo log.
- **Por quê:**
  - Com o Redis fora, é melhor responder `503` em milissegundos do que prender cada exportador por segundos. O exportador já sabe esperar e tentar de novo.
  - Se a ingestão gerasse spans e os mandasse para ela mesma, cada lote recebido geraria outro lote para receber: um laço de realimentação.

## D27. Gravação em lote: COPY para uma tabela temporária, depois INSERT ... ON CONFLICT

- **Escolha:**
  - Cada lote vai por `COPY` para uma tabela temporária (`ON COMMIT DELETE ROWS`).
  - De lá vai para `spans` com `INSERT ... ON CONFLICT DO NOTHING`, numa transação só.
- **Alternativas:**
  - Um `INSERT` por linha, ou `executemany`.
  - `COPY` direto na tabela.
- **Por quê:**
  - O `COPY` é o caminho mais rápido para muitas linhas, mas não sabe ignorar repetidos.
  - Com a tabela temporária no meio, ficam a velocidade de um e a idempotência do outro.
  - O `INSERT` devolve quantas linhas eram novas, e a diferença são os repetidos, contados no log.

## D28. Três tipos de falha, três respostas

- **Escolha:**

  | Falha | Resposta |
  |---|---|
  | Passageira (conexão, desligamento, sem recursos) | Esperar e repetir, de 0,5 s a 10 s, sem confirmar |
  | Dado recusado pelo banco | Dividir o lote ao meio até isolar a linha e descartar só ela |
  | Lote ilegível | Stream de mortos, com o motivo |
  | Erro inesperado | Deixar o processo cair; o Docker reinicia e os pendentes são retomados |

- **Alternativa:** repetir qualquer erro.
- **Por quê:** repetir um erro de dado trava a fila para sempre, e repetir um bug esconde o bug.
- **Detalhe que custou três rodadas (Etapa 3):** a classificação olha o **estado da conexão**, não só o tipo do erro.
  - Uma conexão que falhou só volta ao pool se o erro foi de dado e ela segue aberta.
  - A devolução ao pool nunca pode substituir o erro original.
  - Um `InternalClientError` com a conexão fechada é tratado como queda.

## D29. Janela de horário aceita

- **Escolha:** spans com início entre 3 dias atrás (a retenção) e 10 minutos à frente. O resto é descartado e contado.
- **Por quê:**
  - Um relógio errado numa aplicação criaria partições em datas absurdas.
  - Um horário não preenchido (zero) criaria uma partição em 1970.
  - O que for mais velho que a retenção seria apagado de qualquer jeito.

## D30. Migrações Alembic num contêiner de execução única

- **Escolha:**
  - Todo o esquema, inclusive a hypertable, a retenção e o projeto `demo`, vem de migrações Alembic.
  - Quem as aplica é o contêiner `migrate`, e o processador só sobe depois que ele termina com sucesso.
  - O teste de saúde do banco confere pela rede (`pg_isready -h 127.0.0.1`).
- **Alternativa:** cada processo cria o que falta ao subir.
- **Por quê:**
  - Um só processo mexe no esquema, antes de todos, e cada mudança fica versionada no git.
  - Pela rede, porque, na primeira subida, a imagem do PostgreSQL roda um servidor temporário só local, e o teste pelo socket dizia "pronto" antes da hora.

## D31. Ids em texto hexadecimal e o projeto na chave única

- **Escolha:**
  - `trace_id` e `span_id` como texto hexadecimal.
  - A chave única é `(project_id, trace_id, span_id, start_time)`.
- **Alternativa:** ids em `bytea` (metade do espaço) e chave sem o projeto.
- **Por quê:**
  - O id aparece igual na URL, no log, no Jaeger e no SQL feito à mão.
  - O custo de espaço é aceitável nesta escala, e a compressão do TimescaleDB o reduz.
  - Sem o projeto na chave, um projeto poderia mandar spans com ids de outro e fazer os legítimos serem ignorados como repetidos.

## D32. A chave da loja de demonstração vem de fora do código

- **Escolha:**
  - A chave vem de `TRACEFLOW_DEMO_INGEST_KEY`, e o `traceflow-migrate` a cadastra (só o hash) no projeto demo.
  - Rodar de novo com a mesma chave não muda nada; com outra, troca o hash.
- **Alternativa:** gravar a chave na migração ou no compose.
- **Por quê:**
  - O repositório vai ser público, e uma chave no código deixaria qualquer pessoa mandar dados para a demonstração online.
  - O valor padrão do compose só vale no desenvolvimento.

## D33. Como a ingestão confere chaves

- **Escolha:**
  - Cache de 60 s, e de 10 s para chaves inexistentes.
  - Com o banco fora, uma chave não conhecida recebe 503 com `Retry-After`, nunca 401.
  - Uma chave conhecida continua valendo, com nova tentativa no banco a cada 10 s.
  - Uma consulta só por chave de cada vez (*single-flight*).
- **Alternativas:**
  - Consultar o banco a cada lote.
  - Responder 401 com o banco fora.
  - Espelhar as chaves no Redis.
- **Por quê:**
  - Mil lotes por segundo viram uma consulta por minuto.
  - Um 401 faria o exportador jogar fora dados de chaves válidas.
  - Sem single-flight, o vencimento do cache fazia todos os lotes simultâneos irem ao banco: 45 avisos numa queda de 80 s, contra 3 depois da correção.
  - Espelhar no Redis criaria duas fontes da verdade.
- **Custo:** uma chave revogada vale por até 60 s, medido.

## D34. Catálogo de serviços mantido pelo processador

- **Escolha:**
  - A tabela `services` tem uma linha por projeto, ambiente e serviço, com a primeira e a última vez visto.
  - O processador a atualiza no máximo uma vez por minuto por combinação, em melhor esforço.
- **Alternativa:** `SELECT DISTINCT` na tabela de spans.
- **Por quê:**
  - A lista de ambientes e serviços fica instantânea, sem varrer milhões de linhas.
  - Uma falha no catálogo nunca segura a fila: ele é um índice auxiliar, e os spans são a verdade.

## D35. Sessões e visibilidade

- **Escolha:**
  - **Sessão:** JWT HMAC-SHA256 (segredo de 32 bytes ou mais) com `iat` fracionário, num cookie `HttpOnly`, `SameSite=Lax` e `Secure` em produção.
  - **Revogação:** um marco de tempo na conta (`sessions_revoked_at`).
  - **Login:** 5 erros por e-mail bloqueiam por 15 min; a mesma mensagem e o mesmo tempo existindo ou não a conta.
  - **Visibilidade:** projeto alheio responde 404.
- **Alternativas:**
  - Uma lista de tokens revogados.
  - Limite de tentativas por IP.
  - Responder 403 para projeto alheio.
- **Por quê:**
  - A API já carrega o usuário a cada requisição, então o marco de tempo não custa nada a mais e não exige guardar tokens.
  - O `iat` em segundos inteiros deixava escapar uma sessão criada no mesmo segundo, antes da revogação (achado por teste).
  - O limite por IP engana atrás de proxies.
  - O 403 confirmaria que o projeto existe.
- **Custo:** o limite por e-mail permite bloquear o login de alguém por 15 min, errando a senha de propósito.

## D36. Os tipos do front são gerados do OpenAPI da API

- **Escolha:** `npm run api:types` roda o `openapi-typescript` sobre o `/openapi.json` que o FastAPI publica e grava `web/src/lib/api-types.ts`.
- **Alternativa:** escrever os tipos TypeScript à mão.
- **Por quê:**
  - Os modelos Pydantic são a fonte da verdade.
  - Gerar os tipos a partir deles faz uma mudança na API quebrar a compilação do front, em vez de quebrar a tela em produção.

## D37. Paginação da busca de traces por cursor

- **Escolha:**
  - O cursor é o par (horário, trace_id) do último item.
  - A consulta pede `(start_time, trace_id) < cursor` e um item a mais, para saber se há próxima página.
- **Alternativa:** `LIMIT/OFFSET`.
- **Por quê:**
  - O `OFFSET` fica mais lento a cada página.
  - Com dados chegando o tempo todo, o `OFFSET` faz itens pularem ou se repetirem entre páginas.
  - O plano medido: só a partição recente é lida e a consulta para no `LIMIT` (2,3 ms com 151 mil spans na hora).

## D38. A árvore do trace e o tempo próprio são calculados no backend

- **Escolha:** `traces.py` monta a árvore (profundidade, início relativo, tempo próprio pela união dos intervalos dos filhos, órfãos).
- **Alternativa:** calcular no front.
- **Por quê:**
  - É lógica de domínio, com casos difíceis (filhos em paralelo, pai ausente, ciclos em dado malformado), testada num lugar só.
  - Vai ser reaproveitada pela análise de impacto da Etapa 8.

## D39. Os filtros da busca ficam na URL

- **Escolha:** ambiente, serviço, status, operação, duração mínima e período são parâmetros da URL.
- **Por quê:** um link copiado abre a mesma busca, e o "voltar" do navegador desfaz um filtro.

## D40. Versões com pelo menos duas semanas de lançadas

- **Escolha:** bibliotecas e imagens fixadas numa versão lançada há pelo menos duas semanas. Por exemplo:
  - Next.js 16.3.8, e não a 16.4.2 de cinco dias antes;
  - TanStack Query 5.104.1;
  - Node 24.21.0;
  - TimescaleDB 2.30.1.
- **Por quê:**
  - Uma versão recém-lançada ainda não passou pelo uso de ninguém: é onde aparecem as regressões.
  - Em ataques à cadeia de suprimentos, um pacote comprometido costuma ser descoberto e retirado em dias.

## D41. O retrato ao vivo é gravado e anunciado a cada segundo (SET + PUBLISH)

- **Escolha:** a cada segundo, o processador grava o retrato de cada projeto e ambiente numa chave do Redis (vale 30 s) e o anuncia no canal `traceflow:live`, os dois num pipeline.
- **Alternativas:**
  - só o PUBLISH;
  - a API calcular as métricas consultando o banco a cada segundo.
- **Por quê:**
  - O Pub/Sub entrega só a quem está ouvindo naquele instante. A chave guarda o retrato atual, e uma aba que acabou de abrir o recebe na hora, sem esperar o próximo segundo.
  - O prazo de 30 s faz o retrato sumir se o processador parar, em vez de ficar parecendo atual.
  - Consultar o banco por segundo e por aba multiplicaria a carga pelo número de abas. O agregador em memória faz a conta uma vez, para todo mundo.

## D42. O p95 da série ao vivo usa uma janela deslizante de 10 s

- **Escolha:** cada ponto do gráfico ao vivo tem o p95 dos 10 s até ele. A janela soma o histograma do segundo que entra e subtrai o do que sai.
- **Alternativas:**
  - o p95 de cada segundo isolado;
  - somar os 10 histogramas de novo para cada ponto.
- **Por quê:**
  - Com ~20 requisições num segundo, o p95 pula entre baldes vizinhos e desenha um serrote que não existe no sistema (visto na primeira captura).
  - Somar 10 histogramas por ponto custava 12 ms por retrato com a loja, e 110 ms com 60 serviços, no mesmo laço que consome os spans. A janela deslizante fez 3,7 ms e 32 ms.

## D43. O WebSocket entra com um ticket de uso único e confere a origem

- **Escolha:** o front pede um ticket por REST (com o cookie), que vale 30 s e é apagado no primeiro uso (`GETDEL`). A conexão de uma origem fora de `TRACEFLOW_CORS_ORIGINS` é fechada com o código 1008.
- **Alternativas:**
  - o cookie de sessão no próprio WebSocket;
  - o JWT na URL.
- **Por quê:**
  - Em produção, front e API ficam em domínios diferentes (D24), e o cookie da API pode não ir junto. O ticket funciona em qualquer arranjo.
  - A URL acaba em logs. Um ticket que já foi usado, ou que venceu em 30 s, não serve para nada a quem o encontrar lá. Um JWT serviria por dias.
  - O navegador não aplica CORS ao WebSocket. Sem conferir a origem, uma página de outro site poderia abrir o canal com a sessão de quem a visita (*Cross-Site WebSocket Hijacking*).

## D44. Uma assinatura do Redis por processo e uma fila de 2 retratos por aba

- **Escolha:** o `LiveHub` assina o canal uma vez, por processo da API, e entrega cada retrato às abas daquele projeto e ambiente. Cada aba tem uma fila de no máximo 2 retratos: cheia, o mais velho sai.
- **Alternativas:**
  - uma assinatura por aba;
  - mandar para cada aba em sequência;
  - uma fila sem limite.
- **Por quê:**
  - Uma assinatura por aba multiplicaria as conexões ao Redis.
  - Mandando em sequência, uma aba lenta atrasaria todas as outras.
  - Para dado ao vivo, o retrato mais novo vale mais que todos os anteriores. Uma fila sem limite faria uma aba lenta acumular retratos velhos, e memória, para sempre.

## D45. Ao vivo aproximado, histórico exato

- **Escolha:**
  - O retrato ao vivo calcula os percentis por histogramas (erro abaixo de 10%).
  - O histórico usa `percentile_cont` sobre os spans gravados, com `time_bucket_gapfill`.
  - Cada balde do histórico divide as requisições pelos segundos que ele cobre de fato, e o período para 5 s antes do "agora".
- **Alternativa:** o mesmo cálculo nos dois.
- **Por quê:**
  - O ao vivo precisa de memória fixa e de somar janelas, e o histograma dá as duas coisas.
  - O histórico tem os spans gravados e pode pagar pela conta exata. Quando ficar caro, entram os *continuous aggregates* do TimescaleDB.
  - Os baldes ficam alinhados no relógio, e o período não. Dividindo pelo passo inteiro, o último ponto despencava, porque era um minuto ainda enchendo.
  - Os 5 s de folga cobrem os spans ainda a caminho.

## D46. Gráficos com cores validadas e estados reservados

- **Escolha:**
  - **A paleta dos serviços:**
    - tem 6 cores, conferidas por script (contraste com o fundo, distância para daltonismo);
    - não usa verde nem vermelho, que ficam reservados para estado (saudável, erro);
    - o estado nunca é só cor: o alerta vem com ícone e texto ("acima de 5%"), e o nome do serviço está sempre ao lado da cor dele.
  - **O desenho:**
    - um eixo Y só, com marcas em números redondos;
    - texto sempre na cor de texto, nunca na da série;
    - cada gráfico tem a versão em tabela.
- **Alternativa:** escolher cores a olho e usar as da biblioteca.
- **Por quê:**
  - Um serviço pintado de vermelho pareceria em erro.
  - Contraste e daltonismo dá para calcular, e não para adivinhar.
  - A dica do mouse não pode ser o único caminho até o número.

## D47. Ferramentas de linha de comando ficam nas dependências de desenvolvimento

- **Escolha:** o CLI do shadcn/ui está em `devDependencies`.
- **Por quê:** ele só gera componentes no repositório. Em `dependencies`, trazia 7 vulnerabilidades "altas" para o `npm audit` de produção. Fora dali, o produto ficou com 0.

## D48. Um tique por segundo separa "sem tráfego" de "processamento parado"

- **Escolha:** a cada segundo, depois dos retratos, o processador publica `{"type":"tick"}` no canal ao vivo, mesmo sem tráfego. O LiveHub avisa `{"type":"idle"}` às abas cujo projeto e ambiente não receberam retrato naquele segundo. O front decide pelo sinal mais recente:
  - retrato: "ao vivo";
  - aviso: "sem tráfego";
  - nada por 5 s: "sem sinal do processamento", com os números apagados.
- **Alternativa:** tratar "não chegou nada" como "sem tráfego".
- **Por quê:**
  - Sem tráfego, o processador não publica retrato. A tela ficava em "Conectando..." para sempre.
  - "Não chegou nada" também acontece quando o processador cai. Sem um sinal regular para comparar, as duas situações ficam iguais, mas uma é normal e a outra é problema.
  - O Pub/Sub entrega as mensagens de um canal na ordem: quando o tique chega, os retratos daquele segundo já chegaram.

## D49. Falha de uma ligação é resposta 5xx ou falta de resposta, e não 4xx

- **Escolha:** no mapa (ao vivo e histórico), uma chamada falhou se o código foi 5xx ou se não houve resposta (span `CLIENT` com erro e sem código: conexão recusada, tempo esgotado).
- **Alternativa:** usar o status de erro do span `CLIENT`, como o OpenTelemetry marca.
- **Por quê:**
  - O OpenTelemetry marca como erro, do lado de quem chama, também os 4xx. Mas na loja todos os "erros" das chamadas eram 402 (cartão recusado) e 404 (produto inexistente): respostas legítimas de quem foi chamado.
  - Com eles, a loja saudável apareceria com cerca de 1,5% de falha, e a ligação payments → bank ficaria "doente" por causa de cartões recusados.
  - É o mesmo critério do RED dos serviços: falha do sistema, não do pedido.
  - O critério está em dois lugares (Python no ao vivo, SQL no histórico). Um teste passa os mesmos spans pelos dois e exige o mesmo resultado.

## D50. O catálogo de endereços é gravado no banco e carregado ao subir

- **Escolha:** o processador grava cada par aprendido (endereço → serviço) em `service_addresses`: o novo e o que mudou na hora, e o resto no máximo uma vez por minuto. Ao subir, carrega tudo antes de ler a fila. A migração `0003` cria o catálogo a partir dos spans já gravados.
- **Alternativa:** guardar só em memória e reaprender com o tráfego.
- **Por quê:**
  - Um serviço que caiu não manda spans, então não há como parear de novo. Sem o catálogo gravado, depois de um reinício, ele viraria um nó virtual com o nome do endereço, justamente durante o incidente.
  - O histórico (`GET /map`) também precisa dos nomes, e ele roda na API, não no processador.
  - Medido: com o notifications fora do ar, o processador reiniciado continuou mostrando "notifications · sem resposta".

## D51. "Sem resposta" é uma regra fixa do mapa

- **Escolha:** um serviço conhecido fica "sem resposta" quando, na janela de 10 s:
  - recebeu 5 chamadas ou mais;
  - metade ou mais delas falhou;
  - ele não atendeu nada (nenhum span `SERVER`).
- **Alternativa:** deixar para as regras configuráveis da Etapa 8.
- **Por quê:**
  - É um fato, e não um limiar de gosto: quem depende dele tenta, falha, e ele não registra nada.
  - O mínimo de 5 chamadas evita afirmar isso com pouco sinal.
  - Exigir falha evita marcar como caído um serviço que só perdeu a instrumentação.
  - "Degradado" e "falhando" (limiares de erro e latência) ficam para as regras da Etapa 8.

## D52. O mapa se desenha sozinho, em camadas, a partir só da estrutura

- **Escolha:**
  - **Posições:** o dagre (layout em camadas) calcula da esquerda para a direita, no sentido das chamadas.
  - **Entrada do cálculo:** só quem existe e quem chama quem. Os números (taxa, falha) não entram.
  - **Enquadramento:** o mapa se refaz só quando aparece ou some um nó ou uma ligação.
- **Alternativas:**
  - posições salvas à mão;
  - simulação de forças.
- **Por quê:**
  - Ninguém precisa configurar nada: serviço novo aparece sozinho, no lugar certo.
  - Com as posições dependendo só da estrutura, o mapa não se mexe a cada segundo enquanto os números mudam.
  - Uma simulação de forças é bonita, mas não é estável e não mostra o sentido do fluxo.

## D53. O mapa de um período vai até 6 horas, calculado dos spans brutos

- **Escolha:** `GET /map` agrupa os spans `CLIENT` e `SERVER` do período com `percentile_cont`. A tela oferece 15 min, 1 h e 6 h.
- **Alternativa:** gravar agregados por minuto e por ligação (a tabela `edge_stats_1m` prevista no desenho).
- **Por quê:**
  - Com 1 h de tráfego da loja, a rota responde em 82 ms, com percentis exatos.
  - Um dia inteiro seriam milhões de linhas por consulta. Para 24 h e 3 dias, o próximo passo é a agregação por minuto (ou os continuous aggregates do TimescaleDB), e não pôr no ar uma consulta lenta.

## D54. A histerese conta retratos diferentes do estado atual, e a linha de base só aprende no saudável

- **Escolha:**
  - Um nó muda de estado depois de 3 retratos seguidos **diferentes do estado em vigor**, qualquer que seja o pedido; ao mudar, vale o último.
  - A linha de base do p95 (média móvel exponencial, peso 1/120 por segundo) só aprende quando o estado em vigor **e** a avaliação do segundo são saudáveis, e só vale depois de 30 amostras.
- **Alternativas:**
  - contar só pedidos iguais;
  - aprender sempre que o estado em vigor for saudável.
- **Por quê:**
  - Com o erro oscilando perto de 25%, a avaliação alterna entre degradado e falhando. Contando só pedidos iguais, o contador recomeçaria a cada troca e o nó ficaria "saudável" para sempre.
  - Durante os 3 s da histerese, o estado em vigor ainda é saudável. Aprendendo nesse intervalo, os valores ruins entravam no "normal": um teste mostrou a linha de base subindo de 100 para 125 ms.

## D55. A saúde de um serviço também é medida pelo lado de quem o chama

- **Escolha:** as regras de erro (taxa de erro e disponibilidade) são avaliadas também nas ligações que chegam em cada serviço, e vale o pior lado. A latência não, porque a linha de base foi aprendida do lado do serviço e a visão de quem chama inclui a rede.
- **Alternativa:** só o que o próprio serviço registra.
- **Por quê:**
  - Um serviço que caiu atrás de um balanceador não registra erro nenhum: ele só some. Quem o chama vê 503 desde o primeiro segundo (D9).
  - Medido: com o estoque fora do ar, a causa saía "orders" por 9 s, até a janela de 10 s esvaziar e o "sem resposta" disparar. Com os dois lados, saiu "inventory" em 2 s.

## D56. Um incidente por projeto e ambiente, com o id nascido no processador

- **Escolha:**
  - Um incidente aberto por projeto e ambiente: falhas simultâneas viram um incidente com várias causas.
  - Abre depois da histerese e resolve depois de 30 s com tudo saudável: uma falha que vai e volta continua sendo o mesmo incidente.
  - O id é um uuid gerado no processador. O incidente e os acontecimentos novos são gravados juntos numa transação, de forma idempotente (`ON CONFLICT`). Se o banco falhar, tudo fica guardado e a gravação é repetida no segundo seguinte.
  - Ao subir, o processador retoma os incidentes abertos.
- **Alternativas:**
  - o id vindo do banco (`SERIAL`);
  - um incidente por serviço.
- **Por quê:**
  - Com o id do banco, o incidente só existiria depois de gravado: com o banco lento ou fora, a tela não o mostraria.
  - Um incidente por serviço transformaria uma falha que sobe pela cadeia em três incidentes, quando ela é uma só.

## D57. A evidência e o "antes / durante / depois" são calculados pela API, sob demanda

- **Escolha:**
  - **A evidência:** onde os erros nasceram (o span com falha sem filho com falha).
  - **A comparação:** os 5 min antes, o pior minuto e os 5 min depois de cada rota afetada.
  - **Onde e quando:** a API calcula as duas com SQL sobre os spans quando o incidente é aberto na tela. A comparação fica guardada no incidente quando os 5 min depois já passaram.
- **Alternativa:** o processador calcular e gravar ao resolver.
- **Por quê:**
  - O "depois" só existe 5 min depois de resolver, quando o processador já esqueceu o incidente.
  - Os spans estão gravados, e a conta exata cabe numa consulta.
  - Guardar quando completo evita refazer uma conta que não muda mais.

## D58. O aviso de incidente em qualquer tela vem de uma consulta a cada 5 s

- **Escolha:** a moldura do app consulta os incidentes abertos a cada 5 s. Ela mostra a contagem no menu e um aviso no canto quando um incidente abre ou resolve. O detalhe segundo a segundo continua vindo do retrato pelo WebSocket, nas telas que o mostram.
- **Alternativa:** o WebSocket em todas as telas.
- **Por quê:**
  - O aviso vale para qualquer tela e qualquer ambiente, e o retrato ao vivo é de um ambiente só.
  - Para um aviso, 5 s de atraso não importam, e a consulta é leve.

## D59. Telas que se adaptam: barra lateral em telas largas, painel no celular

- **Escolha:**
  - **Telas largas** (a partir de 1024 px): a barra lateral fixa.
  - **Telas menores:**
    - uma barra no topo, com o botão de menu e o selo dos incidentes abertos;
    - o menu abre num painel lateral, que fecha ao navegar;
    - margens menores;
    - tabelas com rolagem horizontal própria.
- **Alternativa:** só computador.
- **Por quê:**
  - Quem está de plantão recebe o alerta no celular e abre o incidente nele.
  - Um teste de ponta a ponta confere que nada da página passa da largura de um celular.

## D60. As regras da demonstração são só leitura

- **Escolha:** editar regras exige ser dono do projeto. O projeto da demonstração não tem dono, então ninguém as muda.
- **Por quê:** a demonstração é compartilhada. Um visitante que desligasse a detecção estragaria a demonstração do próximo.

## D61. O Playground fala com a loja só pelos hashes de caos, com uma falha por vez

- **Escolha:** a API do Playground só escreve os hashes `demo:chaos:{serviço}` que a loja já relê a cada segundo, o mesmo mecanismo da Etapa 1. As regras:
  - **uma falha por vez**: um `SET NX` com prazo numa chave só decide quem começa, e quem chega depois recebe 409;
  - **toda falha expira sozinha**: a chave e os hashes têm o mesmo prazo, de no máximo 5 minutos;
  - **um limite de 10 falhas a cada 10 minutos por endereço:** os visitantes da demonstração dividem a mesma conta, então o limite não pode ser por usuário;
  - **encerrar não tem restrição**, porque consertar a loja é sempre seguro.
- **Alternativas:**
  - uma API em cada serviço da loja para ligar falhas;
  - verificar e depois gravar ("já tem falha?" e então gravar).
- **Por quê:**
  - A loja continua sem saber que o TraceFlow existe: o caos é o mesmo que se liga pelo terminal.
  - Verificar e depois gravar deixa dois visitantes passarem juntos pela verificação. O `SET NX` é atômico: só um consegue.
  - A demonstração é pública: uma falha esquecida não pode deixar a loja quebrada para o próximo visitante (D22).
- **Custo:** o endereço é o que chega à API. Atrás de um proxy reverso, todos os visitantes chegariam com o endereço do proxy e dividiriam o mesmo limite. Na publicação (Etapa 10), o uvicorn precisa ler o endereço real do cabeçalho do proxy (`--proxy-headers`), confiando só no endereço do próprio proxy (`--forwarded-allow-ips`).

## D62. O gerador de carga relê o ritmo no Redis a cada segundo

- **Escolha:** o gerador de carga lê o hash `demo:traffic` (req/s e fração de compras) a cada segundo, como os serviços leem o caos. Sem o hash, valem as variáveis de ambiente. A tela grava o hash com prazo de 10 minutos.
- **Alternativas:**
  - reiniciar o contêiner com outras variáveis;
  - uma API no gerador.
- **Por quê:**
  - É o mesmo mecanismo do caos, sem nenhum canal novo.
  - O ritmo muda em até 1 s, sem reiniciar nada.
  - O prazo devolve a demonstração ao padrão.
  - Depois de baixar o ritmo, o gerador não "paga a dívida" disparando de uma vez as requisições atrasadas.

## D63. O ciclo do incidente é montado na tela, com a causa esperada vinda da API

- **Escolha:**
  - **A API:** guarda o experimento (o que foi ligado, quando, até quando, e quando acabou) e a causa esperada. Num cenário, ela vem pronta. Numa falha manual, sai do serviço, e o `bank` vira `bank:8000`, porque é externo e aparece pelo endereço.
  - **A tela:** junta o experimento, a lista de incidentes e o retrato ao vivo numa função pura, que diz em que passo está o ciclo e se a causa e a severidade bateram com o esperado.
- **Alternativa:** uma máquina de estados do experimento no backend.
- **Por quê:**
  - Todas as peças já existiam: o incidente, o retrato ao vivo e a recuperação.
  - Uma segunda máquina de estados no servidor duplicaria o que o rastreador de incidentes já faz.
  - A função pura tem testes para cada passo.

## D64. O Playground só existe no projeto da demonstração

- **Escolha:** num projeto próprio, a tela explica e leva ao Playground da demonstração. A API funciona só onde a loja existe (sem o Redis do caos configurado, responde 503).
- **Por quê:** num projeto de verdade, as falhas são as de verdade. O Playground quebra a loja de demonstração, e só ela.

## D65. O freio da contrapressão é a idade da fila, e não o número de lotes

> Revisa a D25 (Etapa 10).

- **Escolha:** a ingestão responde `503` com `Retry-After` quando o lote mais antigo da fila espera há mais de 30 s (`TRACEFLOW_MAX_QUEUE_AGE_S`). A idade sai do id da primeira entrada do stream, que começa pelo horário em que ela entrou, comparado com o `TIME` do próprio Redis. O limite de 50 mil lotes continua como segunda trava e como teto do `MAXLEN`.
- **Alternativas:**
  - contar spans em vez de lotes, com um contador no Redis atualizado na entrada e na confirmação;
  - medir a memória do Redis.
- **Por quê:**
  - O teste de carga mostrou que o freio por lotes nunca disparava: com lotes de 200 spans, 50 mil lotes são 10 milhões de spans, perto de 1,75 GB no Redis. A máquina ficaria sem memória antes. Com os lotes pequenos da loja, isso não aparecia.
  - A idade mede o que importa, o atraso, e vale para lotes de 1 ou de 200 spans. Ela também limita a memória: no máximo 30 s do que chega.
  - Um contador de spans precisaria ser atualizado em dois processos e pode se desencontrar da fila numa queda. A idade sai da própria fila.
  - Medido: com 12 mil spans/s oferecidos (acima da vazão de então), a idade parou em ~35 s, 20,6% dos lotes foram recusados com `503`, e a fila esvaziou 5,6 s depois do fim.

## D66. O processador grava duas leituras ao mesmo tempo

- **Escolha:** o processador roda `TRACEFLOW_WRITERS` (2) laços de leitura no mesmo processo. Enquanto um espera o banco gravar, o outro já normaliza e grava a leitura seguinte. A contagem de spans recusados passou a ser de cada gravação, e não do objeto.
- **Alternativa:** vários processadores (o consumer group do Redis já reparte a fila entre eles).
- **Por quê:**
  - O `/metrics` mostrou o gargalo: no teste de carga, o processador passou 72% do tempo esperando gravações, com só 27% de um núcleo de CPU, enquanto o banco ainda tinha núcleos livres.
  - Dentro de um processo, o retrato ao vivo, o mapa e os incidentes continuam vendo todo o tráfego. Com vários processadores, cada um veria só um pedaço, e seria preciso particionar a fila por trace e juntar os retratos (o "para escalar" da D6).
  - Medido no mesmo teste: de 8.339 para 14.666 spans/s gravados (+76%), e o atraso p95 com 8 mil spans/s caiu de 4,3 s para 1,5 s.

## D67. CI no GitHub Actions, com o banco de verdade e o sistema inteiro

- **Escolha:** a cada push e pull request, em paralelo: o backend (ruff, mypy e pytest com um TimescaleDB de verdade como serviço), a loja e o front (tipos, eslint, Vitest e o build de produção). Depois, o Playwright contra o sistema inteiro subido com o `docker-compose.yml` do projeto. Se ele falhar, o relatório, os traces do Playwright e os logs dos contêineres ficam guardados por 7 dias.
- **Alternativa:** só os testes de unidade, com o banco simulado.
- **Por quê:**
  - Os erros mais caros do projeto só apareceram com o sistema montado (Etapas 6, 8 e 9).
  - No CI, os testes de banco não podem ser pulados em silêncio: com `TRACEFLOW_TEST_REQUIRE_DB=1`, um banco que não subiu faz o teste falhar, em vez de virar um "tudo verde" que não testou nada.
  - O teste de ponta a ponta usa o mesmo Compose de quem roda o projeto: se ele quebrar, o README também quebrou.

## D68. As métricas ficam numa porta interna, com os contadores que já existiam

- **Escolha:** a ingestão, o processador e a API servem `GET /metrics` (formato do Prometheus) na porta 9464 do contêiner, separada da porta pública. Os contadores que iam para o log são lidos na hora da raspagem, sem contagem dupla. As novas métricas são as distribuições: o atraso de cada lote até o banco, o tempo de gravação, o tempo do retrato de cada segundo, a duração das requisições da API (pelo molde da rota, nunca pelo caminho com ids) e as abas conectadas ao vivo.
- **Alternativa:** um `/metrics` na porta pública de cada serviço.
- **Por quê:**
  - Na publicação, o proxy só repassa a porta pública, e as métricas não ficam abertas para a internet.
  - Rotular pela rota real (`/api/projects/42/traces`) criaria uma série nova a cada id. Pelo molde, o número de séries é fixo.
  - O histograma de atraso é o que responde "o pipeline está atrasado?". A média do log escondia a cauda.

## D69. A demonstração pública num servidor só, atrás de um Caddy

> Revisa a D24 (Etapa 10). O usuário escolheu um servidor gratuito da Oracle e nenhum domínio próprio.

- **Escolha:**
  - Tudo num servidor ARM da Oracle Cloud (camada gratuita: 2 núcleos e 12 GB), com o mesmo `docker-compose.yml` do projeto e um complemento de produção (`deploy/docker-compose.prod.yml`).
  - Um **Caddy** é o único serviço aberto para a internet: emite e renova o certificado HTTPS sozinho e manda `/api/*` (inclusive o WebSocket) para a API, `/v1/traces` para a ingestão e o resto para o front. O banco, o Redis, as métricas e a loja não têm porta publicada.
  - O endereço é do **sslip.io**, um DNS gratuito que devolve o IP escrito no próprio nome (`129-146-10-20.sslip.io` aponta para `129.146.10.20`).
  - Os segredos (senha do banco, segredo das sessões, chave da loja) são gerados no servidor pelo `deploy/instalar.sh` e ficam só no `.env` de lá. A API se recusa a subir com cookie seguro e o segredo de desenvolvimento.
- **Alternativas:**
  - **o desenho da D24** (front na Vercel, API num serviço de contêineres): sem domínio próprio, o front ficaria em `*.vercel.app` e a API em outro endereço. O cookie da sessão viraria um cookie de terceiros, que o Safari bloqueia, e o login quebraria no iPhone;
  - um servidor pago (Hetzner, DigitalOcean), mais previsível que a camada gratuita.
- **Por quê:**
  - Com front, API e ingestão no mesmo endereço, o cookie é do próprio site: funciona em qualquer navegador, sem CORS.
  - É exatamente o Compose que roda no PC e no CI: o que foi testado é o que vai para o ar. Antes do servidor, a configuração de produção foi conferida no PC, atrás do Caddy com um certificado local.
  - O custo é zero. O risco é a Oracle mudar a camada gratuita de novo (ela a cortou pela metade em 2026, sem aviso). Por isso a publicação inteira é um script que roda em qualquer Ubuntu.
  - Atrás do Caddy, a API lê o endereço do visitante do `X-Forwarded-For` (D61). Ela aceita esse cabeçalho de qualquer um porque a porta dela não é publicada: só quem está na rede interna a alcança.

## D70. Cor só para estado: os serviços não têm cor própria

> Etapa 10, no redesenho do front pelo brief de design.

- **Escolha:** a paleta do brief (carvão neutro, um destaque, quatro cores de estado), e nenhuma cor por serviço. O serviço é identificado pelo nome, em fonte monoespaçada; o ponto ao lado diz a saúde dele. No waterfall, a barra é cheia no tom do destaque (trabalhando), listrada e neutra (esperando outro serviço) ou vermelha (com erro). Para comparar serviços, um gráfico pequeno por serviço, na mesma escala.
- **Alternativa:** uma paleta de categorias para os serviços, como até a Etapa 9.
- **Por quê:**
  - Uma paleta de serviços foi testada com o validador de paletas e não coube: o verde, o âmbar, o vermelho e os azuis já são de estado e do destaque, e todo laranja, ciano ou magenta ficava perto demais de um estado (ΔE abaixo de 15). Um serviço laranja ao lado de um erro vermelho faria alguém ler "falha" onde não há.
  - O brief pede cor para comunicar estado, e não para decorar. Sem cores de serviço, o vermelho de um erro salta sozinho no waterfall.
  - Gráficos pequenos na mesma escala comparam melhor que várias linhas coloridas sobrepostas, e não precisam de legenda.

## D71. Um espaço de trabalho por projeto: ambiente, período e conexão ao vivo no cabeçalho

- **Escolha:** o ambiente e o período ficam na URL (`?environment=demo&range=6h`) e valem para todas as telas; os links internos os levam junto. A conexão ao vivo (WebSocket) é uma só, aberta pela moldura, e o cabeçalho mostra o estado dela. Os detalhes técnicos abrem ao lado (o trace num painel lateral, o span numa coluna ao lado do waterfall), sem janelas por cima.
- **Alternativa:** cada tela com o seu seletor de ambiente e de período e a sua conexão, como até a Etapa 9.
- **Por quê:**
  - Trocar de tela não perde a escolha, e um link copiado abre a mesma visão.
  - Uma conexão por projeto em vez de uma por tela: o Playground e o detalhe do incidente abriam a sua própria.
  - Investigar é ir e voltar entre a lista e o detalhe; um painel ao lado mantém a lista de vista.
