"""Sessões do SQLAlchemy para as tabelas da aplicação."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(sqlalchemy_url: str) -> AsyncEngine:
    # pool_pre_ping: antes de usar uma conexão parada no pool, confere se ela ainda está viva
    # (o banco pode ter reiniciado enquanto ela esperava)
    return create_async_engine(sqlalchemy_url, pool_size=5, max_overflow=5, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: os objetos continuam legíveis depois do commit, sem nova consulta
    return async_sessionmaker(engine, expire_on_commit=False)
