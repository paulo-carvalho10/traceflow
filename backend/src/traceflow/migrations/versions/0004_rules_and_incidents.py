"""regras de detecção, incidentes e a linha do tempo deles

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As regras padrão (capítulo 11 do guia), as mesmas de traceflow.incidents.rules.DEFAULT_RULES
DEFAULT_RULES_SQL = """
INSERT INTO alert_rules (project_id, target, metric, operator, threshold, relative, min_requests, state)
SELECT p.id, r.target, r.metric, r.operator, r.threshold, r.relative, r.min_requests, r.state
FROM projects p
CROSS JOIN (VALUES
    ('*', 'error_rate', '>=', 0.05, false, 20, 'degraded'),
    ('*', 'p95_ms',     '>=', 2.0,  true,  20, 'degraded'),
    ('*', 'error_rate', '>=', 0.25, false, 20, 'failing')
) AS r(target, metric, operator, threshold, relative, min_requests, state)
"""


def upgrade() -> None:
    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "target", sa.String(200), nullable=False, server_default="*"
        ),  # um serviço, ou * para todos
        sa.Column("metric", sa.String(20), nullable=False),
        sa.Column("operator", sa.String(2), nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("relative", sa.Boolean, nullable=False, server_default="false"),  # x vezes a linha de base
        sa.Column("min_requests", sa.Integer, nullable=False, server_default="20"),
        sa.Column("state", sa.String(20), nullable=False),  # degraded ou failing
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "metric IN ('error_rate', 'p95_ms', 'p99_ms', 'rps', 'availability')", name="metric_ok"
        ),
        sa.CheckConstraint("operator IN ('>=', '<=')", name="operator_ok"),
        sa.CheckConstraint("state IN ('degraded', 'failing')", name="state_ok"),
        sa.CheckConstraint("NOT relative OR metric IN ('p95_ms', 'p99_ms')", name="relative_only_latency"),
    )
    op.create_index("alert_rules_by_project", "alert_rules", ["project_id"])
    op.execute(DEFAULT_RULES_SQL)

    op.create_table(
        "incidents",
        # o id nasce no processador (uuid), e não no banco: o incidente aparece na tela no mesmo
        # segundo em que abre, mesmo que a gravação demore ou precise ser repetida
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment", sa.String(120), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),  # open ou resolved
        sa.Column("severity", sa.String(4), nullable=False),  # a de agora
        sa.Column("peak_severity", sa.String(4), nullable=False),  # a pior que chegou
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("causes", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("affected", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("at_risk", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("endpoints", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("summary", postgresql.JSONB),  # antes / durante / depois, calculado depois de resolvido
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'resolved')", name="status_ok"),
    )
    op.create_index("incidents_by_project", "incidents", ["project_id", sa.text("opened_at DESC")])
    op.create_index(
        "incidents_open", "incidents", ["project_id"], postgresql_where=sa.text("status = 'open'")
    )

    op.create_table(
        "incident_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("incident_events_by_incident", "incident_events", ["incident_id", "at"])


def downgrade() -> None:
    op.drop_table("incident_events")
    op.drop_table("incidents")
    op.drop_table("alert_rules")
