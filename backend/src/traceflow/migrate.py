"""`traceflow-migrate`: aplica as migrações que faltam (alembic upgrade head).

Roda como um contêiner de uma vez só no docker-compose, antes do processador e da API.
Não precisa do alembic.ini: a configuração é montada aqui, então a imagem Docker não
carrega arquivos de desenvolvimento.
"""

from __future__ import annotations

import logging
import time

from alembic import command
from alembic.config import Config

from traceflow.config import Settings, setup_logging

log = logging.getLogger("traceflow.migrate")


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "traceflow:migrations")
    config.set_main_option("sqlalchemy.url", database_url or Settings().sqlalchemy_url)
    return config


def main(attempts: int = 30) -> None:
    """Aplica as migrações, insistindo enquanto o banco ainda não aceita conexões."""
    setup_logging()
    for attempt in range(1, attempts + 1):
        try:
            command.upgrade(alembic_config(), "head")
            return
        except OSError as exc:  # conexão recusada: o banco ainda está subindo
            if attempt == attempts:
                raise
            log.warning("banco ainda indisponível (%s); tentativa %d de %d", exc, attempt, attempts)
            time.sleep(1)


if __name__ == "__main__":
    main()
