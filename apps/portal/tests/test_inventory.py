"""Management works with a provider that has no Kubernetes resource or namespace."""

from dataclasses import dataclass, replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, OTHER, OWNER, SETTINGS, Omnigent

from portal.app import create_app
from portal.controls import SandboxControl, SandboxUpdate
from portal.execution import ExecutionTarget, connect
from portal.integrations import Integrations
from portal.inventory import Sandbox
from portal.sandboxes import Store
from portal.storage import NativeBinding, SandboxIntent, open_store
from portal.storage.database import DatabaseSettings


@dataclass(frozen=True)
class RemoteHandle:
    identity: str


class RemoteProvider:
    provider_instance = "remote-api/team"

    def __init__(self):
        self.handle = RemoteHandle("remote-allocation-42")
        self.sandbox = Sandbox(
            provider="remote",
            name="calm-fox",
            scope="team/project",
            uid="remote-42",
            resource_version="1",
            owner=OWNER,
            title="Remote sandbox",
            created_at=None,
            state="Running",
            message="Ready",
            requested_mode="Running",
            deleting=False,
            allocation=None,
            profile_snapshot=None,
            grants={},
            control=SandboxControl(),
            reference=self.handle,
        )
        self.close = Mock()

    def allocation(self, manifest, *, snapshot=None):
        return None

    def drift(self, saved, reference):
        return False

    def observe(self, binding):
        assert binding == NativeBinding(
            key=self.sandbox.uid, reference={"id": self.handle.identity}
        )
        return self.sandbox

    def plan_mode(self, manifest, mode):
        return manifest

    def usage(self, manifest):
        return {}

    def retained_usage(self, owner, uids):
        return {}

    def get(self, name, owner):
        if (name, owner) != (self.sandbox.name, self.sandbox.owner):
            raise HTTPException(404, "Sandbox not found")
        return self.sandbox

    def admin_get(self, name, scope):
        if scope != self.sandbox.scope:
            raise HTTPException(404, "Sandbox not found")
        return self.get(name, self.sandbox.owner)

    def list(self, owner):
        return [self.sandbox] if owner == self.sandbox.owner else []

    def admin_list(self):
        return [self.sandbox]

    def describe(self, reference):
        assert reference is self.handle
        return self.sandbox

    def status(self, reference, row):
        if reference is None:
            return row
        assert reference is self.handle
        return {**row, "message": "Remote provider reports ready"}

    def configuration(self, reference, result):
        assert reference is self.handle
        return {**result, "desired": {"instance": reference.identity}, "observed": {}}

    def sharing(self, reference, members):
        assert reference is self.handle
        self.sandbox = replace(self.sandbox, grants=members)
        return reference

    def control(self, reference, control, mode):
        assert reference is self.handle
        self.sandbox = replace(self.sandbox, control=control)
        return self.mode(reference, mode) if mode else reference

    def mode(self, reference, mode, **kwargs):
        assert reference is self.handle
        self.sandbox = replace(self.sandbox, requested_mode=mode, state=mode)
        return reference

    def execution(self, reference, *, admin=False):
        assert reference is self.handle
        return ExecutionTarget(
            key=("remote", reference.identity),
            scope=self.sandbox.scope,
            sandbox_uid=self.sandbox.uid,
            connector=lambda command, **kwargs: (reference.identity, command),
        )


@pytest.fixture
def remote_store(tmp_path):
    provider = RemoteProvider()
    registry = object.__new__(Integrations)
    registry.items = {"remote": provider}
    metadata = open_store(DatabaseSettings(url=f"sqlite:///{tmp_path / 'remote.db'}"))
    metadata.migrate()
    record = metadata.reserve_create(
        SandboxIntent(
            id=uuid4(),
            name="calm-fox",
            owner=OWNER,
            scope="team/project",
            provider="remote",
            provider_instance=provider.provider_instance,
            manifest={"instance": provider.handle.identity},
        ),
        uuid4(),
    )
    metadata.confirm_binding(
        record.id,
        NativeBinding(key="remote-42", reference={"id": provider.handle.identity}),
        expected_revision=record.revision,
    )
    store = Store(SETTINGS, integrations=registry, metadata=metadata)
    yield store, provider
    metadata.close()


def test_foreign_inventory_configuration_and_sharing_through_the_api(remote_store):
    store, provider = remote_store
    path = BASE + "/sandboxes/calm-fox"
    with TestClient(create_app(SETTINGS, store, Omnigent())) as browser:
        row = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"][0]
        assert row["id"] == "calm-fox" and row["namespace"] == "team/project"
        assert row["message"] == "Remote provider reports ready"
        assert row["profile"] is None and row["helpers"] == []
        assert "remote-allocation-42" not in str(row)
        assert browser.get(path + "/configuration", headers=HEADERS).json()[
            "desired"
        ] == {"instance": "remote-allocation-42"}
        assert (
            browser.put(
                path + "/sharing", headers=HEADERS, json={"members": {OTHER: "view"}}
            ).status_code
            == 200
        )
        bob = {**HEADERS, "Cookie": "session=bob"}
        shared = browser.get(BASE + "/sandboxes", headers=bob, params={"owner": OWNER})
        assert shared.json()["sandboxes"][0]["can_shell"] is False
        with pytest.raises(HTTPException) as error:
            store.execution("calm-fox", OTHER, OWNER)
        assert error.value.status_code == 404
        browser.put(
            path + "/sharing", headers=HEADERS, json={"members": {OTHER: "shell"}}
        )
        target = store.execution("calm-fox", OTHER, OWNER)
        assert connect(target, ["sh"]) == (provider.handle.identity, ["sh"])
        browser.put(path + "/sharing", headers=HEADERS, json={"members": {}})
        with pytest.raises(HTTPException) as error:
            store.execution("calm-fox", OTHER, OWNER)
        assert error.value.status_code == 404
    provider.close.assert_called_once()


def test_admin_controls_use_foreign_identity_and_block_execution(remote_store):
    store, provider = remote_store
    with pytest.raises(HTTPException) as error:
        store.admin_control(
            "calm-fox",
            "team/project",
            "stale",
            SandboxUpdate(
                resource_version=store.get("calm-fox", OWNER).resource_version,
                disabled=True,
            ),
            OWNER,
        )
    assert error.value.status_code == 409
    changed = store.admin_control(
        "calm-fox",
        "team/project",
        "remote-42",
        SandboxUpdate(
            resource_version=store.get("calm-fox", OWNER).resource_version,
            disabled=True,
        ),
        OWNER,
    )
    assert changed.control.disabled and provider.sandbox.requested_mode == "Suspended"
    with pytest.raises(HTTPException) as error:
        store.execution("calm-fox", OWNER)
    assert error.value.status_code == 403


def test_provider_registry_alias_does_not_duplicate_database_inventory(remote_store):
    store, provider = remote_store
    store.integrations.items["duplicate"] = provider
    assert len(store.list(OWNER)) == 1
    assert store.get("calm-fox", OWNER).owner == OWNER


def test_unknown_provider_never_uses_another_transport(remote_store):
    store, provider = remote_store
    sandbox = replace(provider.sandbox, provider="unavailable")
    with pytest.raises(HTTPException) as error:
        store.integrations.execution(sandbox)
    assert error.value.status_code == 409
