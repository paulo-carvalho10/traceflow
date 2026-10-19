"""Gerador de carga: clientes de mentira usando a loja sem parar.

Funciona em modelo ABERTO: dispara uma requisição a cada 1/RPS segundos, sem esperar as
anteriores terminarem, como usuários de verdade, que não esperam uns pelos outros. No modelo
fechado (cada usuário espera a resposta antes de mandar a próxima), uma loja lenta receberia
menos requisições, e a lentidão sumiria das medições. Isso se chama "coordinated omission".

Configuração por variáveis de ambiente:
    GATEWAY_URL     para onde mandar (padrão http://gateway:8000)
    RPS             requisições por segundo (padrão 20)
    CHECKOUT_RATIO  fração que compra; o resto só olha produtos (padrão 0.3)
    MAX_IN_FLIGHT   limite de requisições pendentes; acima disso, descarta (padrão 500)
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections import Counter

import httpx

PRODUCTS = [f"p{i}" for i in range(1, 9)]
UNKNOWN_PRODUCT_RATIO = 0.02  # um pouco de 404: erro do cliente, que não pode contar como falha da loja
REPORT_EVERY_S = 10.0


class Stats:
    """Contagens e latências da janela atual, impressas a cada REPORT_EVERY_S segundos."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.outcomes: Counter[str] = Counter()
        self.latencies: list[float] = []
        self.started = time.monotonic()

    def record(self, outcome: str, latency_s: float | None = None) -> None:
        self.outcomes[outcome] += 1
        if latency_s is not None:
            self.latencies.append(latency_s)

    def report_if_due(self) -> None:
        elapsed = time.monotonic() - self.started
        if elapsed < REPORT_EVERY_S:
            return
        total = sum(self.outcomes.values())
        ordered = sorted(self.latencies)

        def pct(p: float) -> float:
            return ordered[min(len(ordered) - 1, int(p * len(ordered)))] * 1000 if ordered else 0.0

        detail = " ".join(f"{k}={v}" for k, v in sorted(self.outcomes.items()))
        print(
            f"[loadgen] {total / elapsed:5.1f} req/s  p50={pct(0.5):.0f}ms p95={pct(0.95):.0f}ms  {detail}",
            flush=True,
        )
        self.reset()


def checkout_body() -> dict[str, object]:
    chosen = random.sample(PRODUCTS, k=random.randint(1, 3))
    if random.random() < UNKNOWN_PRODUCT_RATIO:
        chosen[0] = "p999"
    return {
        "email": f"cliente{random.randint(1, 5000)}@exemplo.com",
        "items": [{"product_id": p, "quantity": random.randint(1, 2)} for p in chosen],
    }


async def one_request(client: httpx.AsyncClient, base: str, checkout_ratio: float, stats: Stats) -> None:
    start = time.monotonic()
    try:
        if random.random() < checkout_ratio:
            response = await client.post(f"{base}/checkout", json=checkout_body())
        else:
            response = await client.get(f"{base}/products")
        stats.record(f"{response.status_code // 100}xx", time.monotonic() - start)
    except httpx.HTTPError:
        stats.record("falha_conexao")


async def run() -> None:
    base = os.environ.get("GATEWAY_URL", "http://gateway:8000")
    rps = float(os.environ.get("RPS", "20"))
    checkout_ratio = float(os.environ.get("CHECKOUT_RATIO", "0.3"))
    max_in_flight = int(os.environ.get("MAX_IN_FLIGHT", "500"))
    print(f"[loadgen] {rps:g} req/s em {base}, {checkout_ratio:.0%} compras", flush=True)

    stats = Stats()
    pending: set[asyncio.Task[None]] = set()
    loop = asyncio.get_running_loop()
    async with httpx.AsyncClient(timeout=10.0) as client:
        next_at = loop.time()
        while True:
            if len(pending) < max_in_flight:
                task = asyncio.create_task(one_request(client, base, checkout_ratio, stats))
                pending.add(task)
                task.add_done_callback(pending.discard)
            else:
                stats.record("descartada")  # a loja travou; não acumular infinitamente
            stats.report_if_due()
            next_at += 1 / rps
            await asyncio.sleep(max(0.0, next_at - loop.time()))


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
