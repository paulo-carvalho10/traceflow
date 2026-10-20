"""A API de verdade, contra o banco de teste (conftest.py). Sem o banco, os testes são pulados.

O Redis (limite de tentativas de login) é o fakeredis.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI

from traceflow.api.app import create_app
from traceflow.config import Settings
from traceflow.ingest.keys import KeyVerifier, PostgresKeyLookup
from traceflow.migrate import ensure_demo_key
from traceflow.security import generate_key, parse_key
from traceflow.storage import SpanStore

pytestmark = pytest.mark.db

PASSWORD = "uma-senha-boa-123"


@pytest.fixture
async def app(clean_db: str) -> AsyncIterator[FastAPI]:
    redis = FakeAsyncRedis()
    application = create_app(Settings(database_url=clean_db), redis)
    yield application
    await redis.aclose()


def client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


@asynccontextmanager
async def signed_up(app: FastAPI, email: str = "ana@exemplo.com") -> AsyncIterator[httpx.AsyncClient]:
    """Um navegador com uma conta recém-criada (e, portanto, já logado)."""
    async with client(app) as c:
        response = await c.post(
            "/api/auth/register", json={"email": email, "password": PASSWORD, "name": "Ana"}
        )
        assert response.status_code == 201, response.text
        yield c


# ---------- contas ----------


async def test_cadastro_ja_entra_e_nao_devolve_a_senha(app: FastAPI) -> None:
    async with signed_up(app, "Ana@Exemplo.com") as c:
        me = await c.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == "ana@exemplo.com"  # e-mail guardado em minúsculas
        assert "password" not in me.text and "hash" not in me.text
        cookie = c.cookies.jar._cookies["testserver.local"]["/"]["tf_session"]  # type: ignore[attr-defined]
        assert cookie.has_nonstandard_attr("HttpOnly")


async def test_email_repetido_e_senha_curta_sao_recusados(app: FastAPI) -> None:
    async with signed_up(app), client(app) as c:
        dup = await c.post(
            "/api/auth/register", json={"email": "ANA@exemplo.com", "password": PASSWORD, "name": "x"}
        )
        curta = await c.post(
            "/api/auth/register", json={"email": "b@exemplo.com", "password": "curta", "name": "x"}
        )
    assert (dup.status_code, curta.status_code) == (409, 422)


async def test_login_errado_e_bloqueio_depois_de_5_erros(app: FastAPI) -> None:
    async with signed_up(app):
        pass
    async with client(app) as c:
        for _ in range(5):
            r = await c.post(
                "/api/auth/login", json={"email": "ana@exemplo.com", "password": "errada-errada"}
            )
            assert r.status_code == 401
            assert r.json()["detail"] == "e-mail ou senha incorretos"  # não diz qual dos dois
        bloqueado = await c.post("/api/auth/login", json={"email": "ana@exemplo.com", "password": PASSWORD})
    assert bloqueado.status_code == 429 and int(bloqueado.headers["retry-after"]) > 0


async def test_email_inexistente_tem_a_mesma_resposta(app: FastAPI) -> None:
    async with client(app) as c:
        r = await c.post("/api/auth/login", json={"email": "ninguem@exemplo.com", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["detail"] == "e-mail ou senha incorretos"


async def test_logout_e_cookie_adulterado(app: FastAPI) -> None:
    async with signed_up(app) as c:
        await c.post("/api/auth/logout")
        assert (await c.get("/api/auth/me")).status_code == 401
    async with client(app) as c:
        c.cookies.set("tf_session", "eyJhbGciOiJIUzI1NiJ9.e30.assinatura-falsa")
        assert (await c.get("/api/auth/me")).status_code == 401


async def test_sair_de_todos_os_dispositivos(app: FastAPI) -> None:
    async with signed_up(app) as celular, client(app) as notebook:
        await notebook.post("/api/auth/login", json={"email": "ana@exemplo.com", "password": PASSWORD})
        assert (await notebook.get("/api/auth/me")).status_code == 200
        # o JWT do notebook ainda valeria 12 h; o marco de tempo na conta o invalida já, mesmo
        # que tudo aconteça no mesmo segundo (o "iat" tem fração de segundo)
        old_token = notebook.cookies["tf_session"]
        await celular.post("/api/auth/logout-all")
        notebook.cookies.set("tf_session", old_token)
        assert (await notebook.get("/api/auth/me")).status_code == 401


# ---------- projetos ----------


async def test_projeto_proprio_e_o_demo_aparecem_e_os_dos_outros_nao(app: FastAPI) -> None:
    async with signed_up(app) as ana, signed_up(app, "bia@exemplo.com") as bia:
        criado = (await ana.post("/api/projects", json={"name": "Loja da Ana"})).json()
        assert criado["can_edit"] and criado["slug"].startswith("loja-da-ana-")
        nomes = {p["name"]: p["can_edit"] for p in (await ana.get("/api/projects")).json()}
        assert nomes == {"Loja de demonstração": False, "Loja da Ana": True}
        # a Bia não vê, não edita e nem descobre que o projeto existe (404, não 403)
        assert (await bia.get(f"/api/projects/{criado['id']}")).status_code == 404
        assert (await bia.patch(f"/api/projects/{criado['id']}", json={"name": "minha"})).status_code == 404
        assert (await bia.delete(f"/api/projects/{criado['id']}")).status_code == 404
        # o demo todo mundo lê, mas ninguém edita
        assert (await bia.get("/api/projects/1")).status_code == 200
        assert (await bia.patch("/api/projects/1", json={"name": "meu"})).status_code == 403


async def test_renomear_e_apagar(app: FastAPI) -> None:
    async with signed_up(app) as c:
        pid = (await c.post("/api/projects", json={"name": "Velho"})).json()["id"]
        assert (await c.patch(f"/api/projects/{pid}", json={"name": "Novo"})).json()["name"] == "Novo"
        assert (await c.delete(f"/api/projects/{pid}")).status_code == 204
        assert (await c.get(f"/api/projects/{pid}")).status_code == 404


# ---------- chaves ----------


async def test_chave_aparece_inteira_uma_vez_e_a_ingestao_a_reconhece(app: FastAPI, clean_db: str) -> None:
    async with signed_up(app) as c:
        pid = (await c.post("/api/projects", json={"name": "Com chave"})).json()["id"]
        nova = (await c.post(f"/api/projects/{pid}/keys", json={"name": "produção"})).json()
        parsed = parse_key(nova["key"])
        assert parsed is not None and parsed[0] == nova["prefix"]
        listada = (await c.get(f"/api/projects/{pid}/keys")).json()
        assert len(listada) == 1 and "key" not in listada[0] and parsed[1] not in str(listada)

        lookup = await PostgresKeyLookup.connect(clean_db)
        verifier = KeyVerifier(lookup, ttl_s=0, negative_ttl_s=0)  # sem cache: vê a revogação na hora
        try:
            assert await verifier.project_for(f"Bearer {nova['key']}") == pid
            assert (await c.delete(f"/api/projects/{pid}/keys/{nova['id']}")).status_code == 204
            assert await verifier.project_for(f"Bearer {nova['key']}") is None
            revogada = (await c.get(f"/api/projects/{pid}/keys")).json()[0]
            assert revogada["revoked_at"] is not None and revogada["last_used_at"] is not None
        finally:
            await lookup.close()


async def test_chaves_de_projeto_alheio_sao_inacessiveis(app: FastAPI) -> None:
    async with signed_up(app) as ana, signed_up(app, "bia@exemplo.com") as bia:
        pid = (await ana.post("/api/projects", json={"name": "Da Ana"})).json()["id"]
        assert (await bia.post(f"/api/projects/{pid}/keys", json={"name": "x"})).status_code == 404
        assert (await bia.get("/api/projects/1/keys")).status_code == 403  # demo: lê o projeto, não as chaves


# ---------- visitante da demonstração ----------


async def test_visitante_so_le_o_projeto_demo(app: FastAPI) -> None:
    async with client(app) as c:
        visitor = (await c.post("/api/auth/demo")).json()
        assert visitor["is_demo_visitor"] is True
        assert [p["name"] for p in (await c.get("/api/projects")).json()] == ["Loja de demonstração"]
        assert (await c.post("/api/projects", json={"name": "meu"})).status_code == 403
        assert (await c.post("/api/projects/1/keys", json={"name": "x"})).status_code == 403
        assert (await c.post("/api/auth/logout-all")).status_code == 403
        # e não dá para entrar como visitante pelo login com senha
        r = await c.post("/api/auth/login", json={"email": "visitante@demo.traceflow", "password": PASSWORD})
        assert r.status_code == 401


# ---------- catálogo ----------


async def test_ambientes_e_servicos_vem_do_catalogo(app: FastAPI, clean_db: str) -> None:
    store = await SpanStore.connect(clean_db)
    t = datetime(2026, 10, 20, 12, tzinfo=UTC)
    await store.upsert_services(
        [(1, "demo", "orders", t), (1, "demo", "payments", t), (1, "staging", "orders", t)]
    )
    await store.close()
    async with client(app) as c:
        await c.post("/api/auth/demo")
        envs = (await c.get("/api/projects/1/environments")).json()
        assert {e["name"]: e["services"] for e in envs} == {"demo": 2, "staging": 1}
        so_demo = (await c.get("/api/projects/1/services", params={"environment": "demo"})).json()
        assert [s["name"] for s in so_demo] == ["orders", "payments"]


# ---------- chave da demonstração ----------


async def test_chave_da_demo_vem_de_fora_e_cadastrar_de_novo_nao_muda_nada(clean_db: str) -> None:
    full = generate_key().full
    assert await ensure_demo_key(clean_db, full) == "cadastrada ou atualizada"
    assert await ensure_demo_key(clean_db, full) == "já estava em dia"
    lookup = await PostgresKeyLookup.connect(clean_db)
    try:
        assert await KeyVerifier(lookup, ttl_s=0, negative_ttl_s=0).project_for(f"Bearer {full}") == 1
    finally:
        await lookup.close()


async def test_login_depois_de_sair_de_todos_volta_a_valer(app: FastAPI) -> None:
    async with signed_up(app) as c:
        await c.post("/api/auth/logout-all")
        r = await c.post("/api/auth/login", json={"email": "ana@exemplo.com", "password": PASSWORD})
        assert r.status_code == 200
        assert (await c.get("/api/auth/me")).status_code == 200  # mesmo segundo, sessão nova: vale
