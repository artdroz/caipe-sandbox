"""Migrations use the caller's connection, without logging credential URLs."""

from alembic import context

from portal.storage.schema import metadata

context.configure(
    connection=context.config.attributes["connection"], target_metadata=metadata
)
with context.begin_transaction():
    context.run_migrations()
