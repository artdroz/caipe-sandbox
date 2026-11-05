"""Database selection and bounded connections; URLs never appear in errors."""

import json
from dataclasses import dataclass, field

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = field(default="sqlite:////var/lib/portal/metadata.db", repr=False)
    pool_size: int = 5
    timeout_seconds: int = 5
    expected_backend: str = ""

    def parsed_url(self):
        try:
            url = make_url(self.url)
        except (ArgumentError, TypeError, ValueError):
            raise ValueError("Invalid metadata database URL") from None
        actual = (
            "postgresql"
            if url.drivername in {"postgres", "postgresql", "postgresql+psycopg"}
            else url.get_backend_name()
        )
        if self.expected_backend not in {"", "sqlite", "postgresql"}:
            raise ValueError("Unsupported expected metadata database backend")
        if self.expected_backend and actual != self.expected_backend:
            raise ValueError(
                "Metadata database backend does not match the deployment configuration"
            )
        if url.drivername in {"postgres", "postgresql", "postgresql+psycopg"}:
            if not url.host or not url.database:
                raise ValueError("PostgreSQL requires a host and database name")
            return url.set(drivername="postgresql+psycopg")
        if url.drivername == "sqlite":
            if (
                not url.database
                or not url.database.startswith("/")
                or url.host
                or url.username
                or url.password
                or url.query
            ):
                raise ValueError("SQLite requires an absolute local database file path")
            return url
        raise ValueError("Metadata storage supports only SQLite and PostgreSQL")

    def engine(self):
        if not 1 <= self.pool_size <= 50 or not 1 <= self.timeout_seconds <= 60:
            raise ValueError("Invalid metadata database pool size or timeout")
        url = self.parsed_url()
        sqlite = url.get_backend_name() == "sqlite"
        engine = create_engine(
            url,
            pool_size=self.pool_size,
            max_overflow=0,
            pool_timeout=self.timeout_seconds,
            pool_pre_ping=True,
            hide_parameters=True,
            json_serializer=lambda value: json.dumps(value, allow_nan=False),
            connect_args={"check_same_thread": False, "timeout": self.timeout_seconds}
            if sqlite
            else {"connect_timeout": self.timeout_seconds},
        )
        if sqlite:

            @event.listens_for(engine, "connect")
            def configure(connection, _):
                connection.isolation_level = None
                connection.execute("PRAGMA foreign_keys=ON")

            @event.listens_for(engine, "begin")
            def begin(connection):
                # Serialize writes before reading revisions; read transactions stay light.
                immediate = connection.get_execution_options().get("metadata_write")
                connection.exec_driver_sql("BEGIN IMMEDIATE" if immediate else "BEGIN")

        return engine
