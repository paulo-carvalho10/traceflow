"""Configuração lida das variáveis de ambiente TRACEFLOW_*."""

from __future__ import annotations

import logging

import redis.asyncio as redis
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.backoff import ExponentialBackoff
from redis.retry import Retry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEFLOW_")

    redis_url: str = "redis://localhost:6379/0"

    # Até a Etapa 4 (chaves de API) tudo o que chega é atribuído a este projeto.
    default_project: str = "demo"

    ingest_host: str = "0.0.0.0"
    ingest_port: int = 4318
    # Corpo maior que isso é recusado (413). Vale para o corpo comprimido e para o descomprimido.
    max_body_bytes: int = 4 * 1024 * 1024
    # Lotes esperando o processador. Acima disso a ingestão responde 503 e os exportadores esperam.
    max_backlog: int = 50_000
    backlog_refresh_s: float = 0.25
    retry_after_s: int = 5
    stats_every_s: float = 10.0


def redis_client(url: str, *, retries: int = 1) -> redis.Redis:
    """Cliente do Redis que desiste rápido.

    O padrão do redis-py tenta 3 vezes com espera crescente: com o Redis fora, cada requisição
    da ingestão ficaria segundos presa antes de responder 503. Melhor recusar logo e deixar
    o exportador tentar de novo mais tarde, que é o que ele já sabe fazer.
    """
    return redis.from_url(
        url,
        socket_connect_timeout=1,
        socket_timeout=2,
        retry=Retry(ExponentialBackoff(cap=0.2, base=0.05), retries),
    )


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
