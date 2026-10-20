"""`traceflow-migrate`: aplica as migrações que faltam (alembic upgrade head) e prepara a demonstração.

Roda como um contêiner de uma vez só no docker-compose, antes do processador e da API.
Não precisa do alembic.ini: a configuração é montada aqui, então a imagem Docker não
carrega arquivos de desenvolvimento.
"""

from __future__ import annotations

import asyncio
import logging
import time

import asyncpg
from alembic import command
from alembic.config import Config

from traceflow.config import Settings, setup_logging
from traceflow.security import hash_secret, parse_key

log = logging.getLogger("traceflow.migrate")

DEMO_KEY_NAME = "loja de demonstração"


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "traceflow:migrations")
    config.set_main_option("sqlalchemy.url", database_url or Settings().sqlalchemy_url)
    return config


async def ensure_demo_key(database_url: str, full_key: str) -> str:
    """Cadastra (ou atualiza) a chave da loja no projeto demo. Devolve o que fez.

    A chave vem de uma variável de ambiente, e o banco guarda só o prefixo e o hash.
    Rodar de novo com a mesma chave não muda nada; com outra chave, troca o hash
    (é assim que se gira a chave da demonstração).
    """
    parsed = parse_key(full_key)
    if parsed is None:
        raise ValueError("TRACEFLOW_DEMO_INGEST_KEY fora do formato tf_<8 letras/dígitos>_<segredo>")
    prefix, secret = parsed
    connection = await asyncpg.connect(database_url)
    try:
        demo_id = await connection.fetchval("SELECT id FROM projects WHERE is_demo ORDER BY id LIMIT 1")
        if demo_id is None:
            raise RuntimeError("o projeto demo não existe; as migrações rodaram?")
        status = await connection.execute(
            """
            INSERT INTO api_keys (project_id, name, prefix, secret_hash) VALUES ($1, $2, $3, $4)
            ON CONFLICT (prefix) DO UPDATE SET secret_hash = excluded.secret_hash, revoked_at = NULL
            WHERE api_keys.secret_hash IS DISTINCT FROM excluded.secret_hash
               OR api_keys.revoked_at IS NOT NULL
            """,
            demo_id,
            DEMO_KEY_NAME,
            prefix,
            hash_secret(secret),
        )
    finally:
        await connection.close()
    return "cadastrada ou atualizada" if status.endswith(" 1") else "já estava em dia"


def main(attempts: int = 30) -> None:
    """Aplica as migrações, insistindo enquanto o banco ainda não aceita conexões."""
    setup_logging()
    settings = Settings()
    for attempt in range(1, attempts + 1):
        try:
            command.upgrade(alembic_config(), "head")
            break
        except OSError as exc:  # conexão recusada: o banco ainda está subindo
            if attempt == attempts:
                raise
            log.warning("banco ainda indisponível (%s); tentativa %d de %d", exc, attempt, attempts)
            time.sleep(1)
    if settings.demo_ingest_key:
        result = asyncio.run(ensure_demo_key(settings.database_url, settings.demo_ingest_key))
        log.info("chave da loja de demonstração: %s", result)


if __name__ == "__main__":
    main()
