"""O gerador de carga lendo o ritmo do Playground (o hash demo:traffic no Redis)."""

from __future__ import annotations

from shop.loadgen import Traffic, TrafficConfig

DEFAULT = TrafficConfig(rps=20, checkout_ratio=0.3)


def test_sem_hash_vale_o_padrao() -> None:
    assert TrafficConfig.parse({}, DEFAULT) == DEFAULT


def test_o_hash_muda_o_ritmo_e_os_valores_sao_limitados() -> None:
    assert TrafficConfig.parse({"rps": "40", "checkout_ratio": "0.5"}, DEFAULT) == TrafficConfig(40, 0.5)
    assert TrafficConfig.parse({"rps": "9999", "checkout_ratio": "-1"}, DEFAULT) == TrafficConfig(100, 0)


def test_campo_invalido_fica_com_o_padrao_sem_derrubar_nada() -> None:
    assert TrafficConfig.parse({"rps": "rápido", "checkout_ratio": "0.6"}, DEFAULT) == TrafficConfig(20, 0.6)


async def test_sem_redis_o_polling_nao_faz_nada() -> None:
    traffic = Traffic(DEFAULT, None)
    async with traffic.polling():
        assert traffic.config == DEFAULT
