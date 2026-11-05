"""Keep namespace ownership independent of each micro VM's creator."""

import sqlalchemy as sa
from alembic import op

revision = "0006_scope_ownership"
down_revision = "0005_scope_grants"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sandboxes",
        sa.Column("scope_owner", sa.String(254), nullable=False, server_default=""),
    )
    table = sa.table("sandboxes", sa.column("owner"), sa.column("scope_owner"))
    op.get_bind().execute(table.update().values(scope_owner=table.c.owner))


def downgrade():
    raise RuntimeError(
        "Restore a compatible backup rather than removing namespace ownership"
    )
