"""Initial sandbox intent, sharing and creation-request schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_metadata"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sandboxes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(254), nullable=False),
        sa.Column("name", sa.String(16), nullable=False),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("provider_instance", sa.String(254), nullable=False),
        sa.Column("manifest", sa.JSON, nullable=False),
        sa.Column("profile_snapshot", sa.JSON(none_as_null=True)),
        sa.Column("requested_mode", sa.String(16), nullable=False),
        sa.Column("native_key", sa.String(512)),
        sa.Column("native_reference", sa.JSON(none_as_null=True)),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner", "name", name="uq_sandbox_owner_name"),
        sa.UniqueConstraint(
            "provider", "provider_instance", "native_key", name="uq_sandbox_native"
        ),
        sa.CheckConstraint(
            "requested_mode IN ('running', 'suspended')", name="ck_mode"
        ),
    )
    op.create_table(
        "sandbox_grants",
        sa.Column(
            "sandbox_id", sa.String(36), sa.ForeignKey("sandboxes.id"), primary_key=True
        ),
        sa.Column("principal", sa.String(254), primary_key=True),
        sa.Column("role", sa.String(8), nullable=False),
        sa.CheckConstraint("role IN ('view', 'shell')", name="ck_grant_role"),
    )
    op.create_index("ix_grant_principal", "sandbox_grants", ["principal"])
    op.create_table(
        "creation_requests",
        sa.Column("owner", sa.String(254), primary_key=True),
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "sandbox_id", sa.String(36), sa.ForeignKey("sandboxes.id"), nullable=False
        ),
    )


def downgrade():
    raise RuntimeError(
        "Restore a compatible database backup rather than dropping metadata"
    )
