"""bank: a API externa de um banco. Fica SEM instrumentação de propósito.

Ela representa o que o TraceFlow não enxerga por dentro (uma API de terceiro): não manda spans,
e só aparece no mapa pelas chamadas que o payments faz para ela, como um nó virtual.
Aceita caos como os outros, para simular "o banco ficou lento".
"""

from __future__ import annotations

import random
import uuid

from fastapi import HTTPException
from pydantic import BaseModel

from shop.runtime import Service, simulate_work

svc = Service("bank", telemetry=False)
api = svc.api

DECLINE_RATE = 0.02


class AuthorizeRequest(BaseModel):
    reference: str
    amount: float


class Authorization(BaseModel):
    authorization_id: str


@api.post("/authorize")
async def authorize(request: AuthorizeRequest) -> Authorization:
    await simulate_work(60, 20)
    if random.random() < DECLINE_RATE:
        raise HTTPException(402, "cartão recusado")
    return Authorization(authorization_id=uuid.uuid4().hex[:12])


app = svc.asgi
