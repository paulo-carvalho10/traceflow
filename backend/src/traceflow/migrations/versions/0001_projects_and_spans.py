"""projetos e a hypertable de spans

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    projects = op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # O projeto da loja de demonstração. Até a Etapa 4, todo span que chega é dele.
    op.bulk_insert(projects, [{"id": 1, "slug": "demo", "name": "Loja de demonstração"}])
    op.execute("SELECT setval('projects_id_seq', (SELECT max(id) FROM projects))")

    op.execute(
        """
        CREATE TABLE spans (
            project_id        INTEGER          NOT NULL,
            environment       TEXT             NOT NULL,
            trace_id          TEXT             NOT NULL,
            span_id           TEXT             NOT NULL,
            parent_span_id    TEXT,
            service           TEXT             NOT NULL,
            name              TEXT             NOT NULL,
            kind              TEXT             NOT NULL,
            start_time        TIMESTAMPTZ      NOT NULL,
            duration_ms       DOUBLE PRECISION NOT NULL,
            status            TEXT             NOT NULL,
            status_message    TEXT,
            http_method       TEXT,
            http_route        TEXT,
            http_status_code  INTEGER,
            peer_address      TEXT,
            attributes        JSONB            NOT NULL DEFAULT '{}',
            resource          JSONB            NOT NULL DEFAULT '{}',
            events            JSONB            NOT NULL DEFAULT '[]'
        )
        """
    )
    # Uma partição (chunk) por hora: o insert cai sempre na mais recente, com índices pequenos.
    op.execute("SELECT create_hypertable('spans', by_range('start_time', INTERVAL '1 hour'))")
    # A identidade de um span. O start_time está aqui porque o TimescaleDB exige a coluna de
    # partição em todo índice único; o project_id, para um projeto não "ocupar" ids de outro.
    op.execute("CREATE UNIQUE INDEX spans_identity ON spans (project_id, trace_id, span_id, start_time)")
    op.execute("CREATE INDEX spans_by_trace ON spans (project_id, trace_id)")
    op.execute("CREATE INDEX spans_by_service ON spans (project_id, environment, service, start_time DESC)")
    op.execute(
        "CREATE INDEX spans_roots ON spans (project_id, environment, start_time DESC) "
        "WHERE parent_span_id IS NULL"
    )
    # Partições com mais de 3 dias são apagadas inteiras, sem DELETE linha a linha.
    op.execute("SELECT add_retention_policy('spans', INTERVAL '3 days')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS spans")
    op.drop_table("projects")
