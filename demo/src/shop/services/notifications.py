"""notifications: manda o e-mail de confirmação do pedido. Não chama ninguém."""

from __future__ import annotations

from pydantic import BaseModel

from shop.runtime import Service, simulate_work

svc = Service("notifications")
api = svc.api


class Notification(BaseModel):
    order_id: str
    email: str


@api.post("/send")
async def send(notification: Notification) -> dict[str, bool]:
    await simulate_work(10, 3)
    return {"sent": True}


app = svc.asgi
