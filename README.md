# TraceFlow

**Real-Time Application Observability Platform**
*Understand your systems. Detect issues faster.*

Plataforma de observabilidade para APIs e microsserviços:
- recebe traces no padrão OpenTelemetry, separados por projeto e ambiente;
- mostra o desempenho de cada serviço em tempo real;
- desenha o mapa de dependências sozinha;
- quando algo quebra, abre um incidente com a causa provável, tudo o que foi afetado e a severidade pelo impacto em quem usa.

O diferencial é o **Incident Playground**: uma loja de demonstração com cinco microsserviços, onde você injeta latência, erros ou derruba um serviço e acompanha a falha se espalhar, ser detectada e se recuperar.

> Em construção. O brief do produto está em [docs/BRIEF.md](docs/BRIEF.md), a arquitetura em [docs/ARQUITETURA.md](docs/ARQUITETURA.md) e as decisões, com as alternativas consideradas, em [docs/DECISOES.md](docs/DECISOES.md).

## Rodando a loja de demonstração

Precisa só do Docker.

```bash
docker compose up -d --build
```

| O quê | Onde |
|---|---|
| **O TraceFlow** (entre como visitante, sem cadastro: abre no dashboard ao vivo) | **http://localhost:3000** |
| A loja | http://localhost:8100/products |
| A ingestão do TraceFlow (OTLP/HTTP) | http://localhost:4318/v1/traces |
| O que a ingestão está recebendo | `docker compose logs -f ingest` |
| O que o processador está gravando | `docker compose logs -f processor` |
| O banco (TimescaleDB) | `docker compose exec timescaledb psql -U traceflow -d traceflow` |
| A API e a documentação interativa | http://localhost:8000/docs |
| O tráfego gerado | `docker compose logs -f loadgen` |

Para comparar com o Jaeger, aponte `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` para `http://jaeger:4318/v1/traces` no compose e suba com `docker compose --profile jaeger up -d` (interface em http://localhost:16686).

### Mandando spans de uma aplicação sua

Crie uma conta, um projeto e uma chave de ingestão (pelo http://localhost:8000/docs, por exemplo). Depois, na sua aplicação instrumentada com OpenTelemetry:

```bash
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<a sua chave>
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=desenvolvimento
```

### Injetando falhas

Acompanhe o efeito no dashboard e no mapa de serviços, que se atualizam a cada segundo. Em uns 10 s, um **incidente** abre sozinho (aviso no canto da tela), com a causa provável, as rotas afetadas e a severidade, e resolve sozinho depois de 30 s com tudo saudável.

```bash
# 800 ms a mais em cada requisição do payments
docker compose exec redis redis-cli -n 1 HSET demo:chaos:payments latency_ms 800
# metade das requisições do payments responde 500
docker compose exec redis redis-cli -n 1 HSET demo:chaos:payments error_rate 0.5
# notifications fora do ar
docker compose exec redis redis-cli -n 1 HSET demo:chaos:notifications down 1
# volta ao normal
docker compose exec redis redis-cli -n 1 DEL demo:chaos:payments demo:chaos:notifications
```

### Testes

```bash
cd backend   # ou: cd demo
uv run pytest            # os testes de banco precisam de: docker compose up -d timescaledb
uv run ruff check . && uv run mypy src tests

cd web
npm test                 # Vitest
npm run typecheck && npm run lint
npm run test:e2e         # Playwright: precisa do sistema no ar
```

### Desenvolvendo o front

```bash
cd web
npm install
npm run dev              # http://localhost:3000, recarrega ao salvar
npm run api:types        # gera de novo os tipos a partir da API (http://localhost:8000/openapi.json)
```
