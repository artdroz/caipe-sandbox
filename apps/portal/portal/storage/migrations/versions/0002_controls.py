"""Seed durable portal-wide and per-user access controls and announcements."""

import sqlalchemy as sa
from alembic import op

revision = "0002_controls"
down_revision = "0001_metadata"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        "portal_controls",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("policy", sa.JSON, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.CheckConstraint("id = 'global'", name="ck_controls_singleton"),
        sa.CheckConstraint("revision >= 1", name="ck_controls_revision"),
    )
    op.bulk_insert(table, [{"id": "global", "policy": {}, "revision": 1}])


def downgrade():
    raise RuntimeError(
        "Restore a compatible backup rather than dropping admin controls"
    )
