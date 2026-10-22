"""o catálogo de endereços: qual serviço atende cada endereço chamado

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_addresses",
        sa.Column(
            "project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("environment", sa.String(120), primary_key=True),
        sa.Column("address", sa.Text, primary_key=True),
        sa.Column("service", sa.String(200), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # O catálogo nasce com o que já está gravado: cada CLIENT pareado com o SERVER filho.
    # Se um endereço apontou para mais de um serviço, vale o mais recente.
    op.execute(
        """
        INSERT INTO service_addresses (project_id, environment, address, service, first_seen, last_seen)
        SELECT DISTINCT ON (project_id, environment, address)
               project_id, environment, address, service, first_seen, last_seen
        FROM (
            SELECT c.project_id, c.environment, c.peer_address AS address, s.service,
                   min(c.start_time) AS first_seen, max(c.start_time) AS last_seen
            FROM spans c
            JOIN spans s ON s.project_id = c.project_id AND s.trace_id = c.trace_id
                        AND s.parent_span_id = c.span_id AND s.kind = 'server'
            WHERE c.kind = 'client' AND c.peer_address IS NOT NULL
            GROUP BY 1, 2, 3, 4
        ) AS pares
        ORDER BY project_id, environment, address, last_seen DESC
        """
    )


def downgrade() -> None:
    op.drop_table("service_addresses")
