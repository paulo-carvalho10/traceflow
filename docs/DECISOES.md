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
