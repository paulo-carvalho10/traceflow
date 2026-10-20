"""Os três segredos do TraceFlow e como cada um é guardado.

    senha de usuário   argon2 (lento de propósito): senhas são fracas e precisam resistir a força bruta
    chave de ingestão  SHA-256 (rápido): a chave é longa e aleatória, ninguém a adivinha por tentativa
    sessão             JWT assinado, num cookie httpOnly que o JavaScript da página não lê

Nada aqui fala com banco ou HTTP: são funções puras, testadas sozinhas.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# ---------- senhas ----------

_hasher = PasswordHasher()  # argon2id com os parâmetros recomendados pela biblioteca

MIN_PASSWORD_LENGTH = 10

# Para comparar quando o e-mail não existe: o login leva o mesmo tempo com e sem conta,
# e ninguém descobre quais e-mails estão cadastrados medindo o tempo da resposta.
_DUMMY_HASH = _hasher.hash("senha-que-nao-existe-de-ninguem")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Se os parâmetros do argon2 mudarem numa versão futura, a senha é refeita no próximo login."""
    return _hasher.check_needs_rehash(password_hash)


# ---------- chaves de ingestão ----------

KEY_PATTERN = re.compile(r"^tf_([a-z0-9]{8})_([A-Za-z0-9_-]{24,})$")


@dataclass(frozen=True)
class NewKey:
    full: str  # mostrada uma única vez, na criação
    prefix: str  # guardado em claro: identifica a chave no banco e na tela
    secret_hash: str  # guardado no lugar do segredo


def generate_key() -> NewKey:
    prefix = "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(8))
    secret = secrets.token_urlsafe(24)  # 32 caracteres, 192 bits de aleatoriedade
    return NewKey(full=f"tf_{prefix}_{secret}", prefix=prefix, secret_hash=hash_secret(secret))


def parse_key(full: str) -> tuple[str, str] | None:
    """'tf_<prefixo>_<segredo>' -> (prefixo, segredo), ou None se o formato não bater."""
    match = KEY_PATTERN.match(full.strip())
    return (match.group(1), match.group(2)) if match else None


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def secret_matches(secret: str, secret_hash: str) -> bool:
    # compare_digest leva o mesmo tempo acerte ou erre: nada de descobrir o hash caractere a caractere
    return hmac.compare_digest(hash_secret(secret), secret_hash)


# ---------- sessão ----------

JWT_ALGORITHM = "HS256"


def create_session_token(user_id: int, secret: str, hours: float, now: float | None = None) -> str:
    # "iat" com fração de segundo (a RFC 7519 permite): "sair de todos os dispositivos" precisa
    # separar uma sessão criada meio segundo antes da revogação de uma criada meio segundo depois
    issued = now if now is not None else time.time()
    claims = {"sub": str(user_id), "iat": issued, "exp": issued + hours * 3600}
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


@dataclass(frozen=True)
class Session:
    user_id: int
    issued_at: float


def read_session_token(token: str, secret: str) -> Session | None:
    """Confere a assinatura e a validade. Qualquer alteração no token invalida a assinatura."""
    try:
        claims = jwt.decode(
            token, secret, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "iat", "exp"]}
        )
        return Session(user_id=int(claims["sub"]), issued_at=float(claims["iat"]))
    except (jwt.InvalidTokenError, ValueError):
        return None
