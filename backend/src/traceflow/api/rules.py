"""As regras de detecção de um projeto.

    GET    /api/projects/{id}/rules             quem pode ler o projeto
    POST   /api/projects/{id}/rules             só o dono
    PATCH  /api/projects/{id}/rules/{rule_id}   só o dono (ligar, desligar, mudar o limite)
    DELETE /api/projects/{id}/rules/{rule_id}   só o dono

O processador relê as regras a cada 10 s: uma mudança aqui vale em até 10 s. O projeto da
demonstração não tem dono, então as regras dele são só leitura para todos os visitantes:
ninguém desliga a detecção do próximo visitante.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from traceflow.api.deps import DbDep, EditableProject, ReadableProject
from traceflow.incidents.rules import DEFAULT_RULES
from traceflow.models import AlertRule

router = APIRouter(prefix="/api/projects", tags=["regras"])

Metric = Literal["error_rate", "p95_ms", "p99_ms", "rps", "availability"]


class RuleIn(BaseModel):
    target: str = Field(default="*", min_length=1, max_length=200)
    metric: Metric
    operator: Literal[">=", "<="]
    threshold: float = Field(ge=0)
    relative: bool = False
    min_requests: int = Field(default=20, ge=1, le=100_000)
    state: Literal["degraded", "failing"]
    enabled: bool = True

    @model_validator(mode="after")
    def coherent(self) -> RuleIn:
        if self.relative and self.metric not in ("p95_ms", "p99_ms"):
            raise ValueError("só a latência (p95, p99) pode ser relativa à linha de base")
        if self.relative and (self.operator != ">=" or self.threshold < 1):
            raise ValueError('regra relativa é "pelo menos N vezes a linha de base", com N ≥ 1')
        if self.metric in ("error_rate", "availability") and self.threshold > 1:
            raise ValueError("taxa de erro e disponibilidade vão de 0 a 1 (0,05 = 5%)")
        return self


class RulePatch(BaseModel):
    threshold: float | None = Field(default=None, ge=0)
    min_requests: int | None = Field(default=None, ge=1, le=100_000)
    state: Literal["degraded", "failing"] | None = None
    enabled: bool | None = None


class RuleOut(RuleIn):
    id: int


def rule_out(rule: AlertRule) -> RuleOut:
    return RuleOut(
        id=rule.id, target=rule.target, metric=rule.metric, operator=rule.operator,  # type: ignore[arg-type]
        threshold=rule.threshold, relative=rule.relative, min_requests=rule.min_requests,
        state=rule.state, enabled=rule.enabled,  # type: ignore[arg-type]
    )  # fmt: skip


def default_rules(project_id: int) -> list[AlertRule]:
    """As regras com que todo projeto nasce (as mesmas da migração 0004)."""
    return [
        AlertRule(
            project_id=project_id, target=r.target, metric=r.metric, operator=r.operator,
            threshold=r.threshold, relative=r.relative, min_requests=r.min_requests, state=r.state,
        )
        for r in DEFAULT_RULES
    ]  # fmt: skip


@router.get("/{project_id}/rules")
async def list_rules(project: ReadableProject, db: DbDep) -> list[RuleOut]:
    rules = await db.scalars(
        select(AlertRule).where(AlertRule.project_id == project.id).order_by(AlertRule.id)
    )
    return [rule_out(r) for r in rules]


@router.post("/{project_id}/rules", status_code=201)
async def create_rule(body: RuleIn, project: EditableProject, db: DbDep) -> RuleOut:
    rule = AlertRule(project_id=project.id, **body.model_dump())
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule_out(rule)


@router.patch("/{project_id}/rules/{rule_id}")
async def update_rule(rule_id: int, body: RulePatch, project: EditableProject, db: DbDep) -> RuleOut:
    rule = await _own_rule(db, project.id, rule_id)
    changes = body.model_dump(exclude_none=True)
    try:  # valida a regra inteira, já com a mudança: um limite de 2,0 na taxa de erro não pode passar
        candidate = RuleIn.model_validate({**rule_out(rule).model_dump(exclude={"id"}), **changes})
    except ValidationError as exc:
        raise HTTPException(422, exc.errors()[0]["msg"]) from exc
    for name in changes:
        setattr(rule, name, getattr(candidate, name))
    await db.commit()
    return rule_out(rule)


@router.delete("/{project_id}/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, project: EditableProject, db: DbDep) -> None:
    await db.delete(await _own_rule(db, project.id, rule_id))
    await db.commit()


async def _own_rule(db: DbDep, project_id: int, rule_id: int) -> AlertRule:
    rule = await db.get(AlertRule, rule_id)
    if rule is None or rule.project_id != project_id:
        raise HTTPException(404, "regra não encontrada")
    return rule
