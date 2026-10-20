"""Projetos, chaves de ingestão e o catálogo de ambientes e serviços.

GET    /api/projects                          os seus projetos e o da demonstração
POST   /api/projects                          cria um projeto
GET    /api/projects/{id}
PATCH  /api/projects/{id}                     renomeia
DELETE /api/projects/{id}                     apaga (chaves e catálogo vão junto)
GET    /api/projects/{id}/keys                as chaves, sem o segredo
POST   /api/projects/{id}/keys                cria uma chave: a chave inteira aparece só aqui
DELETE /api/projects/{id}/keys/{key_id}       revoga (a ingestão para de aceitar em até 60 s)
GET    /api/projects/{id}/environments        ambientes vistos nos spans
GET    /api/projects/{id}/services            serviços vistos, por ambiente
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from traceflow.api.deps import DbDep, EditableProject, ReadableProject, UserDep, can_edit, visible_projects
from traceflow.api.schemas import EnvironmentOut, KeyIn, KeyOut, NewKeyOut, ProjectIn, ProjectOut, ServiceOut
from traceflow.models import ApiKey, Project, Service, User
from traceflow.security import generate_key

router = APIRouter(prefix="/api/projects", tags=["projetos"])


def project_out(project: Project, user: User) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        slug=project.slug,
        name=project.name,
        is_demo=project.is_demo,
        can_edit=can_edit(project, user),
        created_at=project.created_at,
    )


def slugify(name: str) -> str:
    """'Loja Nova!' -> 'loja-nova-7k2q' (o sufixo evita colisão entre projetos de nome igual)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:48] or "projeto"
    return f"{base}-{secrets.token_hex(2)}"


@router.get("")
async def list_projects(user: UserDep, db: DbDep) -> list[ProjectOut]:
    return [project_out(p, user) for p in await visible_projects(db, user)]


@router.post("", status_code=201)
async def create_project(body: ProjectIn, user: UserDep, db: DbDep) -> ProjectOut:
    if user.is_demo_visitor:
        raise HTTPException(403, "crie uma conta para ter os seus projetos")
    project = Project(name=body.name.strip(), slug=slugify(body.name), owner_id=user.id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project_out(project, user)


@router.get("/{project_id}")
async def get_project(project: ReadableProject, user: UserDep) -> ProjectOut:
    return project_out(project, user)


@router.patch("/{project_id}")
async def rename_project(body: ProjectIn, project: EditableProject, user: UserDep, db: DbDep) -> ProjectOut:
    project.name = body.name.strip()
    await db.commit()
    return project_out(project, user)


@router.delete("/{project_id}", status_code=204)
async def delete_project(project: EditableProject, db: DbDep) -> None:
    # Os spans do projeto não são apagados aqui: numa hypertable isso seria um DELETE pesado.
    # Sem o projeto, ninguém mais os consulta, e a retenção os apaga em até 3 dias.
    await db.delete(project)
    await db.commit()


@router.get("/{project_id}/keys")
async def list_keys(project: EditableProject, db: DbDep) -> list[KeyOut]:
    keys = await db.scalars(select(ApiKey).where(ApiKey.project_id == project.id).order_by(ApiKey.id))
    return [KeyOut.model_validate(k) for k in keys]


@router.post("/{project_id}/keys", status_code=201)
async def create_key(body: KeyIn, project: EditableProject, db: DbDep) -> NewKeyOut:
    new = generate_key()
    key = ApiKey(
        project_id=project.id, name=body.name.strip(), prefix=new.prefix, secret_hash=new.secret_hash
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    return NewKeyOut(**KeyOut.model_validate(key).model_dump(), key=new.full)


@router.delete("/{project_id}/keys/{key_id}", status_code=204)
async def revoke_key(key_id: int, project: EditableProject, db: DbDep) -> None:
    key = await db.get(ApiKey, key_id)
    if key is None or key.project_id != project.id:
        raise HTTPException(404, "chave não encontrada")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await db.commit()


@router.get("/{project_id}/environments")
async def list_environments(project: ReadableProject, db: DbDep) -> list[EnvironmentOut]:
    rows = await db.execute(
        select(Service.environment, func.count(), func.max(Service.last_seen))
        .where(Service.project_id == project.id)
        .group_by(Service.environment)
        .order_by(func.max(Service.last_seen).desc())
    )
    return [EnvironmentOut(name=env, services=n, last_seen=last) for env, n, last in rows]


@router.get("/{project_id}/services")
async def list_services(
    project: ReadableProject, db: DbDep, environment: str | None = None
) -> list[ServiceOut]:
    query = select(Service).where(Service.project_id == project.id)
    if environment is not None:
        query = query.where(Service.environment == environment)
    services = await db.scalars(query.order_by(Service.environment, Service.name))
    return [ServiceOut.model_validate(s) for s in services]
