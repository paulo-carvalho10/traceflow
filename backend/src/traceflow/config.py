"""Configuração lida das variáveis de ambiente TRACEFLOW_*."""

from __future__ import annotations

import logging

import redis.asyncio as redis
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.backoff import ExponentialBackoff
from redis.retry import Retry


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRACEFLOW_")

    redis_url: str = "redis://localhost:6379/0"

    ingest_host: str = "0.0.0.0"
    ingest_port: int = 4318
    # Corpo maior que isso é recusado (413). Vale para o corpo comprimido e para o descomprimido.
    max_body_bytes: int = 4 * 1024 * 1024
    # Lotes esperando o processador. Acima disso a ingestão responde 503 e os exportadores esperam.
    max_backlog: int = 50_000
    backlog_refresh_s: float = 0.25
    retry_after_s: int = 5
    stats_every_s: float = 10.0

    database_url: str = "postgresql://traceflow:traceflow@localhost:5432/traceflow"

    # Processador
    consumer_name: str = "processor-1"  # fixo: ao reiniciar, ele retoma os próprios pendentes na hora
    read_count: int = 200  # entradas (lotes) por leitura do stream
    read_block_ms: int = 1000
    reclaim_idle_ms: int = 30_000  # pendente parado há mais que isso foi largado por um consumidor que caiu
    reclaim_every_s: float = 10.0
    # Spans fora desta janela são descartados: relógio errado na aplicação criaria partições no passado
    # ou no futuro. O passado acompanha a retenção da tabela de spans.
    accept_past_s: int = 3 * 24 * 3600
    accept_future_s: int = 10 * 60

    # Chaves de ingestão
    key_cache_ttl_s: float = 60.0  # uma chave revogada para de funcionar em até 60 s
    key_negative_cache_ttl_s: float = 10.0  # chave inexistente: não consultar o banco a cada lote
    # A chave da loja de demonstração. Vem de fora (variável de ambiente), nunca do código:
    # o repositório é público. O traceflow-migrate a cadastra no projeto demo.
    demo_ingest_key: str | None = None

    # API e sessões
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # HMAC-SHA256 pede pelo menos 32 bytes de segredo (RFC 7518); menos que isso não sobe
    jwt_secret: str = Field(default="segredo-de-desenvolvimento-troque-em-producao", min_length=32)
    session_hours: float = 12.0
    cookie_name: str = "tf_session"
    cookie_secure: bool = False  # True em produção (só HTTPS)
    cors_origins: list[str] = ["http://localhost:3000"]
    login_max_failures: int = 5
    login_window_s: int = 15 * 60

    # Incident Playground: liga falhas na loja de demonstração (o Redis do caos, banco 1).
    # Sem a URL, o Playground fica desligado (503): num ambiente sem a loja, não há o que quebrar.
    playground_redis_url: str | None = None
    playground_max_fault_s: int = 5 * 60  # toda falha expira sozinha; nunca dura mais que isso
    playground_traffic_ttl_s: int = 10 * 60  # o tráfego mudado volta sozinho ao padrão
    playground_starts_per_window: int = 10  # falhas que um visitante pode iniciar a cada 10 min

    @property
    def sqlalchemy_url(self) -> str:
        """O mesmo banco, no formato que o SQLAlchemy entende (driver asyncpg)."""
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)


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
