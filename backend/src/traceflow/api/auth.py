"""Contas e sessões.

POST /api/auth/register      cria a conta e já entra
POST /api/auth/login         e-mail e senha; no máximo 5 erros por e-mail a cada 15 min
POST /api/auth/demo          entra como visitante da demonstração, sem senha
POST /api/auth/logout        sai deste navegador
POST /api/auth/logout-all    invalida todas as sessões da conta, em todos os aparelhos
GET  /api/auth/me            quem está logado
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from traceflow.api.deps import DbDep, RedisDep, SettingsDep, UserDep
from traceflow.api.schemas import Login, Register, UserOut
from traceflow.config import Settings
from traceflow.models import User
from traceflow.security import create_session_token, hash_password, password_needs_rehash, verify_password

router = APIRouter(prefix="/api/auth", tags=["autenticação"])

WRONG_CREDENTIALS = "e-mail ou senha incorretos"


def start_session(response: Response, user: User, settings: Settings) -> None:
    token = create_session_token(user.id, settings.jwt_secret, settings.session_hours)
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=int(settings.session_hours * 3600),
        httponly=True,  # o JavaScript da página não lê: um script malicioso (XSS) não rouba a sessão
        secure=settings.cookie_secure,  # em produção, só viaja por HTTPS
        samesite="lax",  # não vai em requisições de outros sites que mudam algo (CSRF)
        path="/",
    )


def end_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure, samesite="lax")


@router.post("/register", status_code=201)
async def register(body: Register, response: Response, db: DbDep, settings: SettingsDep) -> UserOut:
    user = User(email=body.email.lower(), name=body.name.strip(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        raise HTTPException(409, "já existe uma conta com este e-mail") from exc
    start_session(response, user, settings)
    return UserOut.model_validate(user)


@router.post("/login")
async def login(
    body: Login, response: Response, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> UserOut:
    email = body.email.lower()
    failures_key = f"traceflow:login:falhas:{email}"
    failures = int(await redis.get(failures_key) or 0)
    if failures >= settings.login_max_failures:
        wait = max(1, await redis.ttl(failures_key))
        raise HTTPException(
            429, "muitas tentativas; espere e tente de novo", headers={"Retry-After": str(wait)}
        )

    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    # verify_password roda o argon2 mesmo sem usuário: o tempo de resposta não revela se o e-mail existe
    if user is None or user.is_demo_visitor or not verify_password(body.password, user.password_hash):
        pipe = redis.pipeline()
        pipe.incr(failures_key)
        pipe.expire(failures_key, settings.login_window_s, nx=True)  # a janela começa no primeiro erro
        await pipe.execute()
        raise HTTPException(401, WRONG_CREDENTIALS)

    await redis.delete(failures_key)
    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        await db.commit()
    start_session(response, user, settings)
    return UserOut.model_validate(user)


@router.post("/demo")
async def demo(response: Response, db: DbDep, settings: SettingsDep) -> UserOut:
    visitor = await db.scalar(select(User).where(User.is_demo_visitor).order_by(User.id).limit(1))
    if visitor is None:
        raise HTTPException(503, "a demonstração não está disponível")
    start_session(response, visitor, settings)
    return UserOut.model_validate(visitor)


@router.post("/logout", status_code=204)
async def logout(response: Response, settings: SettingsDep) -> None:
    end_session(response, settings)


@router.post("/logout-all", status_code=204)
async def logout_all(response: Response, user: UserDep, db: DbDep, settings: SettingsDep) -> None:
    """JWT não se "apaga": ele vale até expirar. Para invalidar, a conta guarda um marco de tempo,
    e toda sessão emitida antes dele é recusada (a API já carrega o usuário a cada requisição)."""
    if user.is_demo_visitor:
        raise HTTPException(403, "o visitante da demonstração não encerra as sessões dos outros visitantes")
    user.sessions_revoked_at = datetime.now(UTC)
    await db.commit()
    end_session(response, settings)


@router.get("/me")
async def me(user: UserDep) -> UserOut:
    return UserOut.model_validate(user)
