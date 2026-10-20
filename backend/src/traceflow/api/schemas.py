"""O que entra e sai da API. Os tipos do front (TypeScript) vão espelhar estes modelos."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from traceflow.security import MIN_PASSWORD_LENGTH


class Register(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    name: str = Field(min_length=1, max_length=120)


class Login(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    is_demo_visitor: bool


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ProjectOut(BaseModel):
    id: int
    slug: str
    name: str
    is_demo: bool
    can_edit: bool  # o front usa para esconder os botões de editar
    created_at: datetime


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class KeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class NewKeyOut(KeyOut):
    key: str  # a chave inteira: aparece só nesta resposta, nunca mais


class EnvironmentOut(BaseModel):
    name: str
    services: int
    last_seen: datetime


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    environment: str
    first_seen: datetime
    last_seen: datetime
