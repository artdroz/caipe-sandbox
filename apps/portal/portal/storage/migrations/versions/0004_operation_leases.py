"""Short database claims for native operations and maintenance."""

import sqlalchemy as sa
from alembic import op

revision = "0004_operation_leases"
down_revision = "0003_sandbox_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_sandbox_scope", "sandboxes", ["provider", "scope"])
    op.create_table(
        "portal_leases",
        sa.Column("name", sa.String(160), primary_key=True),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    raise RuntimeError(
        "Restore a compatible backup rather than removing operation coordination"
    )
