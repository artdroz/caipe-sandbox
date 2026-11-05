"""Require compatible readers before namespace controls contain native policies."""

revision = "0007_namespace_network_policy"
down_revision = "0006_scope_ownership"
branch_labels = None
depends_on = None


def upgrade():
    # Policy intent uses the existing controls JSON; no table change is required.
    pass


def downgrade():
    raise RuntimeError(
        "Restore a compatible backup before removing namespace policy support"
    )
