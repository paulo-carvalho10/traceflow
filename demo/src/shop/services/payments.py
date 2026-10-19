"""payments: cobra o pedido, pedindo autorização ao banco externo."""

from __future__ import annotations

from pydantic import BaseModel

from shop.runtime import Service, call, relay, service_url, simulate_work

svc = Service("payments")
api = svc.api

BANK = service_url("bank")


class ChargeRequest(BaseModel):
    order_id: str
    amount: float


class Payment(BaseModel):
    order_id: str
    authorization_id: str


@api.post("/charge")
async def charge(request: ChargeRequest) -> Payment:
    await simulate_work(5, 2)  # antifraude, regras de parcelamento...
    response = await call(
        svc.http, "POST", f"{BANK}/authorize", json={"reference": request.order_id, "amount": request.amount}
    )
    authorization = relay(response)  # 402 do banco vira 402 daqui: pagamento recusado
    return Payment(order_id=request.order_id, authorization_id=authorization["authorization_id"])


app = svc.asgi
