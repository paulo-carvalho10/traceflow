"""inventory: o catálogo e o estoque. Não chama ninguém."""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from shop.runtime import Service, simulate_work

svc = Service("inventory")
api = svc.api

RESTOCK_BELOW = 50
RESTOCK_TO = 1_000


class Product(BaseModel):
    id: str
    name: str
    price: float


CATALOG = {
    p.id: p
    for p in [
        Product(id="p1", name="Camiseta", price=59.9),
        Product(id="p2", name="Caneca", price=34.5),
        Product(id="p3", name="Boné", price=49.0),
        Product(id="p4", name="Moletom", price=189.9),
        Product(id="p5", name="Adesivos", price=12.0),
        Product(id="p6", name="Garrafa", price=79.9),
        Product(id="p7", name="Mochila", price=249.0),
        Product(id="p8", name="Caderno", price=29.9),
    ]
}
stock = dict.fromkeys(CATALOG, RESTOCK_TO)


class Item(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=10)


class ReserveRequest(BaseModel):
    order_id: str
    items: list[Item] = Field(min_length=1)


class Reservation(BaseModel):
    order_id: str
    amount: float


@api.get("/products")
async def list_products() -> list[Product]:
    await simulate_work(8, 3)  # a "consulta ao banco"
    return list(CATALOG.values())


@api.post("/reserve")
async def reserve(request: ReserveRequest) -> Reservation:
    await simulate_work(15, 5)
    for item in request.items:
        if item.product_id not in CATALOG:
            raise HTTPException(404, f"produto {item.product_id} não existe")
        if stock[item.product_id] < item.quantity:
            raise HTTPException(409, f"sem estoque de {item.product_id}")
    for item in request.items:
        stock[item.product_id] -= item.quantity
        if stock[item.product_id] < RESTOCK_BELOW:
            stock[item.product_id] = RESTOCK_TO  # a demonstração nunca fica sem estoque
    amount = sum(CATALOG[i.product_id].price * i.quantity for i in request.items)
    return Reservation(order_id=request.order_id, amount=round(amount, 2))


app = svc.asgi
