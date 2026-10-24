# Uma imagem para a ingestão, o processador e a API.
# O docker-compose.yml escolhe qual deles cada contêiner roda.
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1º só as dependências: esta camada fica em cache enquanto o pyproject e o lock não mudarem
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2º o código
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# O gerador do teste de carga: a mesma base, mais o grupo "carga" (httpx). Só é construído
# quando pedido (target: carga, no serviço loadtest do Compose).
FROM base AS carga
RUN uv sync --frozen --no-dev --group carga
COPY loadtest ./loadtest

# A imagem de produção: o último estágio é o que se constrói sem escolher um alvo.
FROM base
