"""usuários, chaves de ingestão e o catálogo de serviços

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VISITOR_EMAIL = "visitante@demo.traceflow"


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(200)),
        sa.Column("is_demo_visitor", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sessions_revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # O visitante da demonstração: entra sem senha (POST /api/auth/demo) e só lê o projeto demo.
    op.bulk_insert(users, [{"email": VISITOR_EMAIL, "name": "Visitante", "is_demo_visitor": True}])

    op.add_column(
        "projects", sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"))
    )
    op.add_column("projects", sa.Column("is_demo", sa.Boolean, nullable=False, server_default="false"))
    op.create_index("projects_by_owner", "projects", ["owner_id"])
    op.execute("UPDATE projects SET is_demo = true WHERE slug = 'demo'")

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("prefix", sa.String(8), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "services",
        sa.Column(
            "project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("environment", sa.String(120), primary_key=True),
        sa.Column("name", sa.String(200), primary_key=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # O catálogo nasce com o que já está gravado (os spans da Etapa 3).
    op.execute(
        """
        INSERT INTO services (project_id, environment, name, first_seen, last_seen)
        SELECT project_id, environment, service, min(start_time), max(start_time)
        FROM spans GROUP BY project_id, environment, service
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("services")
    op.drop_table("api_keys")
    op.drop_index("projects_by_owner", "projects")
    op.drop_column("projects", "is_demo")
    op.drop_column("projects", "owner_id")
    op.drop_table("users")
