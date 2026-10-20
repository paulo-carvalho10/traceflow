"""As tabelas da aplicação, como classes SQLAlchemy.

A tabela de spans não está aqui: ela é uma hypertable do TimescaleDB, escrita em lote e
consultada com SQL feito à mão (asyncpg). O ORM fica com o que é CRUD: usuários, projetos,
chaves e o catálogo de serviços (e, nas próximas etapas, regras e incidentes).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # sempre em minúsculas
    name: Mapped[str] = mapped_column(String(120))
    # vazio para o visitante da demonstração, que entra sem senha
    password_hash: Mapped[str | None] = mapped_column(String(200))
    is_demo_visitor: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # sessões emitidas antes disso não valem mais ("sair de todos os dispositivos")
    sessions_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    projects: Mapped[list[Project]] = relationship(back_populates="owner")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    # o projeto da demonstração não tem dono: é do sistema, e qualquer pessoa logada pode ler
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped[User | None] = relationship(back_populates="projects")
    keys: Mapped[list[ApiKey]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    prefix: Mapped[str] = mapped_column(String(8), unique=True)  # a parte da chave guardada em claro
    secret_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 do segredo, nunca o segredo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="keys")


class Service(Base):
    """O catálogo: cada serviço que já mandou spans, por projeto e ambiente.

    Mantido pelo processador. Responde "quais ambientes e serviços este projeto tem?"
    sem varrer milhões de spans.
    """

    __tablename__ = "services"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    environment: Mapped[str] = mapped_column(String(120), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
