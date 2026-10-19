"""orders: monta o pedido. Reserva o estoque, cobra e avisa o cliente, nessa ordem."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from pydantic import BaseModel, Field

from shop.runtime import Service, call, relay, service_url, simulate_work

svc = Service("orders")
api = svc.api

INVENTORY = service_url("inventory")
PAYMENTS = service_url("payments")
NOTIFICATIONS = service_url("notifications")


class Item(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=10)


class OrderRequest(BaseModel):
    email: str
    items: list[Item] = Field(min_length=1)


class Order(BaseModel):
    order_id: str
    amount: float
    authorization_id: str
    notified: bool


@api.post("/orders", status_code=201)
async def create_order(request: OrderRequest) -> Order:
    order_id = uuid.uuid4().hex[:12]
    await simulate_work(4, 1)

    items = [i.model_dump() for i in request.items]
    reservation = relay(
        await call(svc.http, "POST", f"{INVENTORY}/reserve", json={"order_id": order_id, "items": items})
    )
    payment = relay(
        await call(
            svc.http,
            "POST",
            f"{PAYMENTS}/charge",
            json={"order_id": order_id, "amount": reservation["amount"]},
        )
    )
    notified = await notify(order_id, request.email)

    return Order(
        order_id=order_id,
        amount=reservation["amount"],
        authorization_id=payment["authorization_id"],
        notified=notified,
    )


async def notify(order_id: str, email: str) -> bool:
    """O e-mail não pode derrubar uma compra já paga: se falhar, o pedido segue sem aviso.

    A falha continua visível no trace (o span CLIENT para notifications fica com erro), mas
    o orders responde 201. Nem toda dependência é crítica, e a análise de impacto precisa
    saber diferenciar isso.
    """
    try:
        response = await call(
            svc.http, "POST", f"{NOTIFICATIONS}/send", json={"order_id": order_id, "email": email}
        )
    except HTTPException:
        return False
    return response.is_success


app = svc.asgi
