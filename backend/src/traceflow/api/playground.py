"""O Incident Playground: quebrar a loja de demonstração de propósito, pela tela.

    GET    /api/playground                  o estado: cenários, a falha em andamento, a última, o tráfego
    POST   /api/playground/scenarios/{id}   inicia um cenário pronto
    POST   /api/playground/faults           inicia uma falha montada à mão
    DELETE /api/playground/faults           encerra a falha em andamento
    PUT    /api/playground/traffic          muda o ritmo do gerador de carga
    DELETE /api/playground/traffic          volta o ritmo ao padrão

Uma falha é um hash demo:chaos:{serviço}, que cada serviço da loja relê a cada segundo
(Etapa 1). O Playground só escreve esses hashes, com três regras, porque a demonstração é
pública e compartilhada (D22):
- **uma falha por vez**: um SET NX numa chave só decide quem começa; quem chega depois
  recebe 409, sem corrida entre dois visitantes;
- **toda falha expira sozinha** (EXPIRE, no máximo 5 min): ninguém deixa a loja quebrada
  para o próximo visitante;
- **um limite por visitante**: 10 inícios a cada 10 minutos (429).
Encerrar uma falha não tem restrição: consertar a loja é sempre seguro.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from traceflow.api.deps import UserDep
from traceflow.config import Settings

router = APIRouter(prefix="/api/playground", tags=["playground"])

ACTIVE_KEY = "playground:active"  # a falha em andamento (existe enquanto ela dura)
LAST_KEY = "playground:last"  # a última falha, para a tela contar o ciclo inteiro depois de acabar
LAST_TTL_S = 30 * 60
TRAFFIC_KEY = "demo:traffic"  # o gerador de carga relê a cada segundo (demo/src/shop/loadgen.py)
RATE_WINDOW_S = 10 * 60
# O padrão do gerador de carga (as variáveis RPS e CHECKOUT_RATIO do docker-compose.yml)
DEFAULT_RPS = 20.0
DEFAULT_CHECKOUT_RATIO = 0.3
# O gateway fica de fora: a porta de entrada fora do ar derrubaria a demonstração inteira
FaultService = Literal["orders", "inventory", "payments", "notifications", "bank"]
FAULT_SERVICES: tuple[str, ...] = ("orders", "inventory", "payments", "notifications", "bank")


# Como cada serviço da loja aparece no mapa: o bank não manda spans, então é um nó externo,
# conhecido pelo endereço que os outros chamam (Etapa 7)
NODE_OF = {"bank": "bank:8000"}


def chaos_key(service: str) -> str:
    return f"demo:chaos:{service}"


class Fault(BaseModel):
    latency_ms: int = 0
    error_rate: float = 0.0
    down: bool = False

    def as_hash(self) -> dict[Any, Any]:  # Any: o tipo de chave do redis-py é uma união invariante
        return {
            "latency_ms": str(self.latency_ms),
            "error_rate": str(self.error_rate),
            "down": "1" if self.down else "0",
        }


class Scenario(BaseModel):
    id: str
    title: str
    description: str
    faults: dict[str, Fault]
    expect_cause: list[str]  # os nós que a análise deve apontar
    expect_severity: Literal["SEV1", "SEV2", "SEV3"]
    watch: str  # o que observar enquanto acontece


SCENARIOS = [
    Scenario(
        id="pagamentos-instaveis",
        title="Pagamentos instáveis",
        description="30% das cobranças do payments respondem erro.",
        faults={"payments": Fault(error_rate=0.3)},
        expect_cause=["payments"],
        expect_severity="SEV1",
        watch="O erro nasce no payments e sobe pelo orders até o gateway: três serviços doentes, "
        "uma causa só.",
    ),
    Scenario(
        id="banco-lento",
        title="Banco lento",
        description="O banco externo passa a responder 1,5 s mais devagar.",
        faults={"bank": Fault(latency_ms=1500)},
        expect_cause=["bank:8000"],
        expect_severity="SEV2",
        watch="O checkout fica lento, sem erro nenhum. A causa é um sistema externo, que nunca mandou um "
        "span: o TraceFlow o enxerga pelas chamadas que chegam nele.",
    ),
    Scenario(
        id="email-fora",
        title="E-mail fora do ar",
        description="O notifications cai: as chamadas para ele falham.",
        faults={"notifications": Fault(down=True)},
        expect_cause=["notifications"],
        expect_severity="SEV3",
        watch="O e-mail cai, mas as compras seguem: o incidente é SEV3, porque quem usa não sente.",
    ),
    Scenario(
        id="estoque-fora",
        title="Estoque fora do ar",
        description="O inventory cai: a vitrine e o checkout dependem dele.",
        faults={"inventory": Fault(down=True)},
        expect_cause=["inventory"],
        expect_severity="SEV1",
        watch="A vitrine e o checkout falham. O serviço caído não registra nada; quem o chama, sim.",
    ),
]
SCENARIOS_BY_ID = {s.id: s for s in SCENARIOS}


class Experiment(BaseModel):
    id: str
    kind: Literal["scenario", "manual"]
    scenario_id: str | None
    title: str
    faults: dict[str, Fault]
    expect_cause: list[str]  # o que a análise deve apontar (a tela confere se acertou)
    expect_severity: Literal["SEV1", "SEV2", "SEV3"] | None  # só nos cenários prontos
    started_at: datetime
    expires_at: datetime
    ended_at: datetime | None = None
    ended_by: Literal["expired", "stopped"] | None = None


class Traffic(BaseModel):
    rps: float
    checkout_ratio: float
    custom: bool  # mudado pela tela (volta sozinho ao padrão em expires_at)
    expires_at: datetime | None
    default_rps: float = DEFAULT_RPS
    default_checkout_ratio: float = DEFAULT_CHECKOUT_RATIO


class PlaygroundState(BaseModel):
    scenarios: list[Scenario]
    services: list[str]
    active: Experiment | None
    last: Experiment | None
    traffic: Traffic
    max_fault_s: int


class StartScenario(BaseModel):
    duration_s: int = Field(default=180, ge=30, le=300)


class ManualFault(BaseModel):
    service: FaultService
    kind: Literal["latency", "errors", "down"]
    latency_ms: int = Field(default=1000, ge=100, le=5000)
    error_rate: float = Field(default=0.3, gt=0, le=1)
    duration_s: int = Field(default=180, ge=30, le=300)


class TrafficIn(BaseModel):
    rps: float = Field(ge=1, le=60)
    checkout_ratio: float = Field(ge=0, le=0.9)


def playground_redis(request: Request) -> redis.Redis:
    client: redis.Redis | None = request.app.state.playground_redis
    if client is None:
        raise HTTPException(503, "o Playground está desligado neste ambiente (sem a loja de demonstração)")
    return client


PlaygroundRedis = Annotated[redis.Redis, Depends(playground_redis)]


@router.get("")
async def state(request: Request, user: UserDep, r: PlaygroundRedis) -> PlaygroundState:
    return await _state(r, request.app.state.settings)


@router.post("/scenarios/{scenario_id}")
async def start_scenario(
    scenario_id: str, request: Request, user: UserDep, r: PlaygroundRedis, body: StartScenario | None = None
) -> PlaygroundState:
    scenario = SCENARIOS_BY_ID.get(scenario_id)
    if scenario is None:
        raise HTTPException(404, "cenário não encontrado")
    duration = (body or StartScenario()).duration_s
    await _start(
        r, request, "scenario", scenario.id, scenario.title, scenario.faults, duration,
        scenario.expect_cause, scenario.expect_severity,
    )  # fmt: skip
    return await _state(r, request.app.state.settings)


@router.post("/faults")
async def start_fault(
    body: ManualFault, request: Request, user: UserDep, r: PlaygroundRedis
) -> PlaygroundState:
    if body.kind == "latency":
        fault, what = Fault(latency_ms=body.latency_ms), f"+{body.latency_ms} ms"
    elif body.kind == "errors":
        fault, what = Fault(error_rate=body.error_rate), f"{round(body.error_rate * 100)}% de erro"
    else:
        fault, what = Fault(down=True), "fora do ar"
    expect = [NODE_OF.get(body.service, body.service)]
    title = f"{body.service}: {what}"
    await _start(r, request, "manual", None, title, {body.service: fault}, body.duration_s, expect, None)
    return await _state(r, request.app.state.settings)


@router.delete("/faults")
async def stop_fault(request: Request, user: UserDep, r: PlaygroundRedis) -> PlaygroundState:
    raw = await r.get(ACTIVE_KEY)
    if raw is not None:
        experiment = Experiment.model_validate_json(raw)
        ended = experiment.model_copy(update={"ended_at": datetime.now(UTC), "ended_by": "stopped"})
        pipe = r.pipeline(transaction=True)
        pipe.delete(ACTIVE_KEY, *(chaos_key(s) for s in experiment.faults))
        pipe.set(LAST_KEY, ended.model_dump_json(), ex=LAST_TTL_S)
        await pipe.execute()
    return await _state(r, request.app.state.settings)


@router.put("/traffic")
async def set_traffic(
    body: TrafficIn, request: Request, user: UserDep, r: PlaygroundRedis
) -> PlaygroundState:
    settings: Settings = request.app.state.settings
    pipe = r.pipeline(transaction=True)
    fields: dict[Any, Any] = {"rps": str(body.rps), "checkout_ratio": str(body.checkout_ratio)}
    pipe.hset(TRAFFIC_KEY, mapping=fields)
    pipe.expire(TRAFFIC_KEY, settings.playground_traffic_ttl_s)
    await pipe.execute()
    return await _state(r, settings)


@router.delete("/traffic")
async def reset_traffic(request: Request, user: UserDep, r: PlaygroundRedis) -> PlaygroundState:
    await r.delete(TRAFFIC_KEY)
    return await _state(r, request.app.state.settings)


async def _start(
    r: redis.Redis,
    request: Request,
    kind: Literal["scenario", "manual"],
    scenario_id: str | None,
    title: str,
    faults: dict[str, Fault],
    duration_s: int,
    expect_cause: list[str],
    expect_severity: Literal["SEV1", "SEV2", "SEV3"] | None,
) -> None:
    settings: Settings = request.app.state.settings
    duration_s = min(duration_s, settings.playground_max_fault_s)
    # O limite é por endereço: os visitantes da demonstração dividem a mesma conta de visitante
    who = request.client.host if request.client else "desconhecido"
    rate_key = f"playground:starts:{who}"
    starts = await r.incr(rate_key)
    if starts == 1:
        await r.expire(rate_key, RATE_WINDOW_S)
    if starts > settings.playground_starts_per_window:
        raise HTTPException(429, "muitas falhas seguidas: espere alguns minutos para começar outra")

    now = datetime.now(UTC)
    experiment = Experiment(
        id=str(uuid.uuid4()), kind=kind, scenario_id=scenario_id, title=title, faults=faults,
        expect_cause=expect_cause, expect_severity=expect_severity,
        started_at=now, expires_at=now + timedelta(seconds=duration_s),
    )  # fmt: skip
    payload = experiment.model_dump_json()
    # SET NX: só um visitante consegue; a falha some sozinha no mesmo prazo que a chave
    if not await r.set(ACTIVE_KEY, payload, nx=True, ex=duration_s):
        raise HTTPException(409, "já há uma falha em andamento: espere ela acabar ou encerre-a")
    pipe = r.pipeline(transaction=True)
    pipe.delete(*(chaos_key(s) for s in FAULT_SERVICES))  # nada sobrando de uma falha anterior
    for service, fault in faults.items():
        pipe.hset(chaos_key(service), mapping=fault.as_hash())
        pipe.expire(chaos_key(service), duration_s)
    pipe.set(LAST_KEY, payload, ex=LAST_TTL_S)
    await pipe.execute()


async def _state(r: redis.Redis, settings: Settings) -> PlaygroundState:
    pipe = r.pipeline(transaction=False)
    pipe.get(ACTIVE_KEY)
    pipe.get(LAST_KEY)
    pipe.hgetall(TRAFFIC_KEY)
    pipe.ttl(TRAFFIC_KEY)
    raw_active, raw_last, raw_traffic, traffic_ttl = await pipe.execute()
    now = datetime.now(UTC)
    active = Experiment.model_validate_json(raw_active) if raw_active else None
    last = Experiment.model_validate_json(raw_last) if raw_last else None
    if last is not None and last.ended_at is None and (active is None or active.id != last.id):
        # a chave da falha sumiu sem ninguém encerrar: ela expirou
        ended_at = min(now, last.expires_at)
        last = last.model_copy(update={"ended_at": ended_at, "ended_by": "expired"})
    traffic_fields = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                      for k, v in (raw_traffic or {}).items()}  # fmt: skip
    custom = bool(traffic_fields)
    return PlaygroundState(
        scenarios=SCENARIOS,
        services=list(FAULT_SERVICES),
        active=active,
        last=last,
        traffic=Traffic(
            rps=float(traffic_fields.get("rps", DEFAULT_RPS)),
            checkout_ratio=float(traffic_fields.get("checkout_ratio", DEFAULT_CHECKOUT_RATIO)),
            custom=custom,
            expires_at=now + timedelta(seconds=traffic_ttl)
            if custom and traffic_ttl and traffic_ttl > 0
            else None,
        ),
        max_fault_s=settings.playground_max_fault_s,
    )
