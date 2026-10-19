"""O orders traduz a falha de cada dependência numa resposta própria."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from shop.services import orders

ORDER = {"email": "a@b.com", "items": [{"product_id": "p1", "quantity": 2}]}
Handler = Callable[[httpx.Request], httpx.Response]


def healthy(request: httpx.Request) -> httpx.Response:
    match request.url.host:
        case "inventory":
            return httpx.Response(200, json={"order_id": "x", "amount": 119.8})
        case "payments":
            return httpx.Response(200, json={"order_id": "x", "authorization_id": "auth1"})
        case "notifications":
            return httpx.Response(200, json={"sent": True})
    raise AssertionError(f"chamada inesperada para {request.url}")


def failing(host: str, failure: Callable[[httpx.Request], httpx.Response]) -> tuple[Handler, list[str]]:
    """Todas as dependências saudáveis, menos `host`. Também anota quem foi chamado."""
    called: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request.url.host)
        return failure(request) if request.url.host == host else healthy(request)

    return handler, called


def refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("conexão recusada", request=request)


def too_slow(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("demorou", request=request)


async def post_order(handler: Handler) -> httpx.Response:
    orders.svc.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=orders.app), base_url="http://orders"
    ) as c:
        return await c.post("/orders", json=ORDER)


async def test_pedido_completo() -> None:
    response = await post_order(healthy)
    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == 119.8 and body["authorization_id"] == "auth1" and body["notified"] is True


async def test_email_fora_do_ar_nao_derruba_a_compra() -> None:
    handler, called = failing("notifications", refused)
    response = await post_order(handler)
    assert response.status_code == 201
    assert response.json()["notified"] is False
    assert called == ["inventory", "payments", "notifications"]


async def test_pagamento_recusado_volta_402_com_o_motivo() -> None:
    handler, _ = failing("payments", lambda r: httpx.Response(402, json={"detail": "cartão recusado"}))
    response = await post_order(handler)
    assert response.status_code == 402
    assert response.json()["detail"] == "cartão recusado"


async def test_estoque_fora_do_ar_vira_502_e_nada_e_cobrado() -> None:
    handler, called = failing("inventory", refused)
    response = await post_order(handler)
    assert response.status_code == 502
    assert called == ["inventory"]


@pytest.mark.parametrize(
    ("failure", "status"),
    [(too_slow, 504), (lambda r: httpx.Response(503, json={"detail": "fora do ar"}), 502)],
    ids=["timeout", "5xx"],
)
async def test_falha_no_pagamento_vira_erro_do_orders(
    failure: Callable[[httpx.Request], httpx.Response], status: int
) -> None:
    handler, called = failing("payments", failure)
    response = await post_order(handler)
    assert response.status_code == status
    assert "payments" in response.json()["detail"]
    assert "notifications" not in called
