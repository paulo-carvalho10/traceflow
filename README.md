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
| A loja | http://localhost:8100/products |
| A ingestão do TraceFlow (OTLP/HTTP) | http://localhost:4318/v1/traces |
| O que a ingestão está recebendo | `docker compose logs -f ingest` |
| O que o processador está gravando | `docker compose logs -f processor` |
| O banco (TimescaleDB) | `docker compose exec timescaledb psql -U traceflow -d traceflow` |
| O tráfego gerado | `docker compose logs -f loadgen` |

Para comparar com o Jaeger, aponte `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` para `http://jaeger:4318/v1/traces` no compose e suba com `docker compose --profile jaeger up -d` (interface em http://localhost:16686).

### Injetando falhas

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
```
