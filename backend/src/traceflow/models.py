"""As tabelas da aplicação, como classes SQLAlchemy.

A tabela de spans não está aqui: ela é uma hypertable do TimescaleDB, escrita em lote e
consultada com SQL feito à mão (asyncpg). O ORM fica com o que é CRUD: projetos e, a partir
da Etapa 4, usuários, chaves, regras e incidentes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
