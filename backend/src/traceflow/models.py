"""As tabelas da aplicação, como classes SQLAlchemy.

A tabela de spans não está aqui: ela é uma hypertable do TimescaleDB, escrita em lote e
consultada com SQL feito à mão (asyncpg). O ORM fica com o que é CRUD: usuários, projetos,
chaves, os catálogos, as regras de detecção e os incidentes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class ServiceAddress(Base):
    """O catálogo de endereços: qual serviço atende cada endereço chamado (live/topology.py).

    Mantido pelo processador, que o aprende pareando spans CLIENT e SERVER. Gravado para
    sobreviver a reinícios: um serviço que caiu não manda spans, então não daria para
    aprender o nome dele de novo. Endereço sem linha aqui é um nó virtual no mapa.
    """

    __tablename__ = "service_addresses"

    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    environment: Mapped[str] = mapped_column(String(120), primary_key=True)
    address: Mapped[str] = mapped_column(Text, primary_key=True)
    service: Mapped[str] = mapped_column(String(200))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertRule(Base):
    """Uma regra de detecção: "se a métrica de um serviço passar do limite, ele fica neste estado".

    Avaliada pelo processador a cada segundo (traceflow/incidents/rules.py). Um projeto nasce
    com as regras padrão; o dono pode mudar, desligar ou acrescentar.
    """

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    target: Mapped[str] = mapped_column(String(200), default="*")  # um serviço, ou * para todos
    metric: Mapped[str] = mapped_column(String(20))
    operator: Mapped[str] = mapped_column(String(2))
    threshold: Mapped[float] = mapped_column(Float)
    relative: Mapped[bool] = mapped_column(Boolean, default=False)  # threshold x a linha de base
    min_requests: Mapped[int] = mapped_column(Integer, default=20)
    state: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Incident(Base):
    """Um incidente: aberto, atualizado e resolvido pelo processador (traceflow/incidents/tracker.py)."""

    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    environment: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(4))
    peak_severity: Mapped[str] = mapped_column(String(4))
    title: Mapped[str] = mapped_column(String(300))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    causes: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    affected: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    at_risk: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    endpoints: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IncidentEvent(Base):
    """Um acontecimento na linha do tempo de um incidente: abriu, mudou a causa, recuperou..."""

    __tablename__ = "incident_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
