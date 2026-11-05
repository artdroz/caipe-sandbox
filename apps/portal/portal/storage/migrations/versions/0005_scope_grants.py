"""Share an owner/provider scope without widening existing permissions."""

import sqlalchemy as sa
from alembic import op

revision = "0005_scope_grants"
down_revision = "0004_operation_leases"
branch_labels = None
depends_on = None


def upgrade():
    target = op.create_table(
        "scope_grants",
        sa.Column("owner", sa.String(254), primary_key=True),
        sa.Column("provider", sa.String(40), primary_key=True),
        sa.Column("provider_instance", sa.String(254), primary_key=True),
        sa.Column("scope", sa.String(512), primary_key=True),
        sa.Column("principal", sa.String(254), primary_key=True),
        sa.Column("role", sa.String(8), nullable=False),
        sa.CheckConstraint("role IN ('view', 'shell')", name="ck_scope_grant_role"),
    )
    op.create_index("ix_scope_grant_principal", "scope_grants", ["principal"])
    connection = op.get_bind()
    source = sa.table(
        "sandboxes",
        *(
            sa.column(name)
            for name in (
                "id",
                "owner",
                "provider",
                "provider_instance",
                "scope",
                "deleted_at",
            )
        ),
    )
    old = sa.table(
        "sandbox_grants",
        sa.column("sandbox_id"),
        sa.column("principal"),
        sa.column("role"),
    )
    connection.execute(
        source.update()
        .where(source.c.scope == "")
        .values(scope="sandbox/" + source.c.id)
    )
    fields = ("owner", "provider", "provider_instance", "scope")
    sibling = source.alias("sibling")
    total = (
        sa.select(sa.func.count())
        .where(
            *(sibling.c[field] == source.c[field] for field in fields),
            sibling.c.deleted_at.is_(None),
        )
        .correlate(source)
        .scalar_subquery()
    )
    role = sa.case(
        (sa.func.min(sa.case((old.c.role == "shell", 1), else_=0)) == 1, "shell"),
        else_="view",
    )
    # Retain only access already granted to every live allocation in the scope.
    existing = (
        sa.select(*(source.c[field] for field in fields), old.c.principal, role)
        .select_from(source.join(old, old.c.sandbox_id == source.c.id))
        .where(source.c.deleted_at.is_(None))
        .group_by(*(source.c[field] for field in fields), old.c.principal)
        .having(sa.func.count(source.c.id) == total)
    )
    connection.execute(
        target.insert().from_select([*fields, "principal", "role"], existing)
    )
    op.drop_table("sandbox_grants")


def downgrade():
    raise RuntimeError(
        "Restore a compatible backup rather than narrowing namespace sharing"
    )
