"""Intended sandbox state, access controls and interrupted operations."""

import sqlalchemy as sa
from alembic import op

revision = "0003_sandbox_state"
down_revision = "0002_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sandboxes",
        sa.Column("scope", sa.String(512), nullable=False, server_default=""),
    )
    for name in ("resource_usage", "control"):
        op.add_column(
            "sandboxes", sa.Column(name, sa.JSON, nullable=False, server_default="{}")
        )
    op.add_column("sandboxes", sa.Column("operation", sa.JSON(none_as_null=True)))
    op.add_column("sandboxes", sa.Column("deleted_at", sa.DateTime(timezone=True)))


def downgrade():
    raise RuntimeError("Restore a compatible backup rather than dropping sandbox state")
