"""A API do TraceFlow (`traceflow-api`, porta 8000). A documentação interativa fica em /docs."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from traceflow.api import auth, projects, traces
from traceflow.config import Settings, setup_logging
from traceflow.config import redis_client as make_redis_client
from traceflow.db import make_engine, make_sessionmaker

log = logging.getLogger("traceflow.api")

DEV_SECRET = Settings.model_fields["jwt_secret"].default


def create_app(settings: Settings | None = None, redis_client: redis.Redis | None = None) -> FastAPI:
    settings = settings or Settings()
    owns_redis = redis_client is None
    engine = make_engine(settings.sqlalchemy_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.jwt_secret == DEV_SECRET:
            log.warning("TRACEFLOW_JWT_SECRET é o segredo de desenvolvimento: troque antes de publicar")
        yield
        await engine.dispose()
        if owns_redis:
            await app.state.redis.aclose()

    app = FastAPI(title="TraceFlow · API", version="0.5.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.redis = redis_client or make_redis_client(settings.redis_url)
    # O front fica em outro endereço (na Vercel, em produção): o navegador só deixa ele chamar
    # a API, levando o cookie, se a origem estiver nesta lista.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(traces.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        async with app.state.sessionmaker() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


def main() -> None:
    setup_logging()
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port, access_log=False)


if __name__ == "__main__":
    main()
