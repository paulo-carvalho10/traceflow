"""gateway: a porta de entrada da loja. É aqui que cada trace começa."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from shop.runtime import Service, call, relay, service_url

svc = Service("gateway")
api = svc.api

INVENTORY = service_url("inventory")
ORDERS = service_url("orders")


class Item(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=10)


class Checkout(BaseModel):
    email: str
    items: list[Item] = Field(min_length=1)


@api.get("/products")
async def products() -> Any:
    return relay(await call(svc.http, "GET", f"{INVENTORY}/products"))


@api.post("/checkout", status_code=201)
async def checkout(request: Checkout) -> Any:
    return relay(await call(svc.http, "POST", f"{ORDERS}/orders", json=request.model_dump()))


app = svc.asgi
