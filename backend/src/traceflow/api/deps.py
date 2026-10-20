"""Dependências das rotas: a sessão do banco, quem está logado e o que essa pessoa pode ver.

Regra de visibilidade: um projeto que você não pode ver responde 404, não 403.
O 403 confirmaria que o projeto existe; o 404 não diz nada a quem não deveria saber.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from traceflow.config import Settings
from traceflow.models import Project, User
from traceflow.security import read_session_token

NOT_FOUND = "projeto não encontrado"


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> redis.Redis:
    client: redis.Redis = request.app.state.redis
    return client


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


SettingsDep = Annotated[Settings, Depends(get_settings)]
RedisDep = Annotated[redis.Redis, Depends(get_redis)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


async def current_user(request: Request, db: DbDep, settings: SettingsDep) -> User:
    token = request.cookies.get(settings.cookie_name)
    session = read_session_token(token, settings.jwt_secret) if token else None
    if session is None:
        raise HTTPException(401, "faça login")
    user = await db.get(User, session.user_id)
    if user is None or _revoked(user.sessions_revoked_at, session.issued_at):
        raise HTTPException(401, "sessão encerrada, faça login de novo")
    return user


def _revoked(revoked_at: datetime | None, issued_at: float) -> bool:
    # comparação com fração de segundo: em segundos inteiros, uma sessão criada no mesmo
    # segundo, antes da revogação, escaparia dela
    return revoked_at is not None and issued_at < revoked_at.timestamp()


UserDep = Annotated[User, Depends(current_user)]


def can_read(project: Project, user: User) -> bool:
    return project.is_demo or project.owner_id == user.id


def can_edit(project: Project, user: User) -> bool:
    return project.owner_id == user.id and not user.is_demo_visitor


async def readable_project(project_id: int, user: UserDep, db: DbDep) -> Project:
    project = await db.get(Project, project_id)
    if project is None or not can_read(project, user):
        raise HTTPException(404, NOT_FOUND)
    return project


async def editable_project(project: Annotated[Project, Depends(readable_project)], user: UserDep) -> Project:
    if not can_edit(project, user):
        raise HTTPException(403, "este projeto é só leitura para você")
    return project


ReadableProject = Annotated[Project, Depends(readable_project)]
EditableProject = Annotated[Project, Depends(editable_project)]


async def visible_projects(db: AsyncSession, user: User) -> list[Project]:
    query = select(Project).where((Project.owner_id == user.id) | Project.is_demo).order_by(Project.id)
    return list((await db.scalars(query)).all())
