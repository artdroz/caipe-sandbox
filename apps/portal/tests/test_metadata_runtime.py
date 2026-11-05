"""Application startup checks metadata without changing its schema or native state."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, OWNER, SETTINGS, Omnigent

from portal.app import create_app
from portal.sandboxes import Store
from portal.storage import SchemaMismatch
from portal.storage.database import DatabaseSettings


def test_postgresql_selection_rejects_sqlite_before_opening_a_file(tmp_path):
    path = tmp_path / "must-not-create.db"
    url = f"sqlite:///{path}"
    with pytest.raises(ValueError, match="backend does not match"):
        DatabaseSettings(url=url, expected_backend="postgresql").engine()
    with pytest.raises(ValueError, match="backend does not match"):
        create_app(replace(SETTINGS, database_url=url, database_backend="postgresql"))
    result = subprocess.run(
        [sys.executable, "-m", "portal.storage", "migrate"],
        env={
            **os.environ,
            "PORTAL_DATABASE_URL": url,
            "PORTAL_DATABASE_BACKEND": "postgresql",
        },
        capture_output=True,
        text=True,
    )
    assert (
        result.returncode == 1
        and "Invalid metadata database configuration" in result.stderr
    )
    assert str(path) not in result.stderr and not path.exists()


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_postgresql_selection_accepts_supported_driver_names(scheme):
    settings = DatabaseSettings(
        url=f"{scheme}://portal:private-password@host/metadata",
        expected_backend="postgresql",
    )
    assert settings.parsed_url().drivername == "postgresql+psycopg"
    assert "private-password" not in repr(settings)


def test_backend_mismatch_errors_do_not_include_credentials():
    with pytest.raises(ValueError, match="backend does not match") as error:
        DatabaseSettings(
            url="postgresql://portal:private-password@host/metadata",
            expected_backend="sqlite",
        ).parsed_url()
    assert "private-password" not in str(error.value)
    with pytest.raises(ValueError, match="Unsupported expected"):
        DatabaseSettings(expected_backend="typo").parsed_url()


def test_startup_requires_migration_and_closes_owned_clients(tmp_path):
    settings = replace(SETTINGS, database_url=f"sqlite:///{tmp_path / 'metadata.db'}")
    integrations = SimpleNamespace(close=Mock())
    store = Store(settings, integrations=integrations)
    store.metadata.close = Mock(wraps=store.metadata.close)
    with pytest.raises(RuntimeError, match="strategy.type=Recreate"):
        with TestClient(create_app(settings, store, Omnigent())):
            pass
    integrations.close.assert_called_once()
    store.metadata.close.assert_called_once()
    with pytest.raises(SchemaMismatch):
        store.metadata.check_schema()


def test_migrated_database_starts_without_provider_or_kubernetes_access(tmp_path):
    settings = replace(SETTINGS, database_url=f"sqlite:///{tmp_path / 'metadata.db'}")
    integrations = SimpleNamespace(close=Mock())
    store = Store(settings, integrations=integrations)
    store.metadata.migrate()
    store.metadata.close = Mock(wraps=store.metadata.close)
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        assert browser.get("/readyz").status_code == 200
        assert browser.get("/healthz").status_code == 200
    integrations.close.assert_called_once()
    store.metadata.close.assert_called_once()


def test_database_credentials_are_absent_from_settings_repr():
    settings = replace(
        SETTINGS, database_url="postgresql://portal:private-password@host/metadata"
    )
    assert "private-password" not in repr(settings)


def test_saved_admin_controls_survive_application_restart(tmp_path):
    settings = replace(
        SETTINGS,
        database_url=f"sqlite:///{tmp_path / 'metadata.db'}",
        admin_emails=json.dumps([OWNER]),
    )

    def portal_store():
        return Store(
            settings,
            integrations=SimpleNamespace(
                items={},
                cleanup_namespaces=Mock(),
                close=Mock(),
            ),
        )

    first = portal_store()
    first.metadata.migrate()
    with TestClient(create_app(settings, first, Omnigent())) as browser:
        body = {
            "resource_version": "1",
            "creation_disabled": True,
            "sandboxes_disabled": False,
            "reason": "Maintenance",
            "announcement": {"title": "Admin message", "body": "Save your work"},
        }
        assert (
            browser.put(
                BASE + "/admin/controls", headers=HEADERS, json=body
            ).status_code
            == 200
        )
    restarted = portal_store()
    with TestClient(create_app(settings, restarted, Omnigent())) as browser:
        saved = browser.get(BASE + "/admin/sandboxes", headers=HEADERS).json()[
            "controls"
        ]
        assert saved["resource_version"] == "2" and saved["creation_disabled"]
        assert saved["announcement"]["title"] == "Admin message"
        assert (
            browser.put(
                BASE + "/admin/controls", headers=HEADERS, json=body
            ).status_code
            == 409
        )
        assert browser.get("/readyz").status_code == 200
