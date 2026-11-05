"""Saved intent converges without replacing identities or bypassing coordination."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_inventory import remote_store as remote_store
from test_portal import BASE, HEADERS, OTHER, OWNER, Kubernetes, Omnigent
from test_profiles import store_for
from test_storage import database as database

from portal.app import create_app
from portal.storage import Conflict, PendingOperation, open_store


@pytest.fixture
def setup(database):
    kube = Kubernetes()
    kube.metadata.close()
    kube.metadata = open_store(database)
    kube.metadata.migrate()
    store, _ = store_for(kube=kube)
    store.settings = replace(store.settings, reconcile_interval_seconds=0)
    sandbox = store.create(OWNER)
    try:
        yield store, kube, sandbox
    finally:
        store.close()
        kube.metadata.close()


def drift(kube, sandbox):
    native = kube.items[(sandbox.scope, sandbox.name)]
    native["spec"]["podTemplate"]["spec"]["containers"][0]["image"] = "out-of-band:v2"
    return native


def test_sync_restores_saved_spec_and_metadata_preserving_defaults_and_identity(setup):
    store, kube, sandbox = setup
    native = drift(kube, sandbox)
    native["metadata"]["annotations"]["sandbox.caipe.io/owner"] = "incorrect"
    native["metadata"]["labels"]["sandbox.caipe.io/profile"] = "incorrect"
    native["metadata"]["annotations"]["another-controller/example"] = "preserved"
    native["spec"]["podTemplate"]["spec"]["dnsPolicy"] = "ClusterFirst"
    patch = Mock(wraps=kube.patch_namespaced_custom_object)
    kube.patch_namespaced_custom_object = patch
    store.profiles.get = Mock(
        side_effect=AssertionError("Sync must not apply today's profile")
    )
    result = store.sync(sandbox.name, OWNER, sandbox.uid, sandbox.record.revision)
    assert not result.configuration_drift and result.uid == sandbox.uid
    assert store.metadata.get_sandbox(sandbox.record.id) == sandbox.record
    assert (
        result.reference["spec"]["podTemplate"]["spec"]["dnsPolicy"] == "ClusterFirst"
    )
    assert (
        result.reference["metadata"]["annotations"]["another-controller/example"]
        == "preserved"
    )
    patch.assert_called_once()
    body = patch.call_args.args[-1]
    assert body["metadata"]["uid"] == sandbox.uid
    assert body["metadata"]["resourceVersion"] == "1"
    assert body["spec"] == sandbox.record.manifest["spec"]
    assert store.reconcile_resources() == []
    patch.assert_called_once()


def test_periodic_pass_repairs_drift_without_a_browser_or_db_revision_change(setup):
    store, kube, sandbox = setup
    drift(kube, sandbox)["spec"]["operatingMode"] = "Suspended"
    assert store.reconcile_resources() == []
    result = store.get(sandbox.name, OWNER)
    assert not result.configuration_drift and result.requested_mode == "Running"
    assert result.reference["spec"]["operatingMode"] == "Running"
    assert result.record == sandbox.record


@pytest.mark.parametrize("problem", ["missing", "replaced", "outage", "provider"])
def test_sync_never_recreates_missing_or_ambiguous_compute(setup, problem):
    store, kube, sandbox = setup
    native = drift(kube, sandbox)
    backend = store.integrations.items["agentSandbox"]
    if problem == "missing":
        del kube.items[(sandbox.scope, sandbox.name)]
    elif problem == "replaced":
        native["metadata"]["uid"] = "different-allocation"
    elif problem == "provider":
        native["metadata"]["annotations"]["sandbox.caipe.io/backend"] = "openShell"
    else:
        backend.observe = Mock(side_effect=HTTPException(503, "Unavailable"))
    kube.patch_namespaced_custom_object = Mock(
        side_effect=AssertionError("No native writes")
    )
    backend.create = Mock(side_effect=AssertionError("Must not recreate"))
    backend.delete = Mock(side_effect=AssertionError("Must not delete"))
    assert store.reconcile_resources() == [
        {"name": sandbox.name, "namespace": sandbox.scope}
    ]
    assert store.metadata.get_sandbox(sandbox.record.id) == sandbox.record
    kube.patch_namespaced_custom_object.assert_not_called()


def test_pending_operations_and_stale_manual_requests_are_not_overwritten(setup):
    store, kube, sandbox = setup
    drift(kube, sandbox)
    patch = Mock(wraps=kube.patch_namespaced_custom_object)
    kube.patch_namespaced_custom_object = patch
    for uid, revision in [("stale-uid", sandbox.record.revision), (sandbox.uid, 999)]:
        with pytest.raises(Conflict, match="changed"):
            store.sync(sandbox.name, OWNER, uid, revision)
    store.metadata.begin_operation(
        sandbox.record.id,
        PendingOperation(
            kind="mode", request_id="00000000-0000-0000-0000-000000000001", actor=OWNER
        ),
        expected_revision=sandbox.record.revision,
        manifest=sandbox.record.manifest,
        requested_mode="suspended",
        resource_usage=sandbox.record.resource_usage,
    )
    assert store.reconcile_resources() == []
    with pytest.raises(Conflict, match="pending operation"):
        store.sync(sandbox.name, OWNER, sandbox.uid, sandbox.record.revision)
    patch.assert_not_called()


@pytest.mark.parametrize("change", ["revision", "lease", "control", "drain"])
def test_changes_during_observation_prevent_dispatch(setup, monkeypatch, change):
    store, kube, sandbox = setup
    drift(kube, sandbox)
    backend = store.integrations.items["agentSandbox"]
    observe = backend.observe
    stopping = threading.Event()

    def intervene(binding):
        result = observe(binding)
        if change == "revision":
            store.metadata.set_scope_grants(
                sandbox.record.id,
                {OTHER: "view"},
                expected_revision=sandbox.record.revision,
            )
        elif change == "lease":
            monkeypatch.setattr(store.metadata, "renew_lease", lambda *a, **kw: False)
        elif change == "control":
            store.metadata.save_controls(
                {"sandboxes_disabled": True}, expected_revision=1
            )
        else:
            stopping.set()
        return result

    backend.observe = intervene
    kube.patch_namespaced_custom_object = Mock(
        side_effect=AssertionError("Must not dispatch")
    )
    with pytest.raises((Conflict, HTTPException)):
        store._sync(sandbox.record, stopping=stopping.is_set)
    kube.patch_namespaced_custom_object.assert_not_called()


def test_native_preconditions_reject_a_resource_changed_after_observation(setup):
    store, kube, sandbox = setup
    native = drift(kube, sandbox)
    patch = kube.patch_namespaced_custom_object

    def race(*args, **kwargs):
        native["metadata"]["resourceVersion"] = "2"
        return patch(*args, **kwargs)

    kube.patch_namespaced_custom_object = race
    with pytest.raises(HTTPException) as error:
        store.sync(sandbox.name, OWNER, sandbox.uid, sandbox.record.revision)
    assert error.value.status_code == 409
    assert (
        native["spec"]["podTemplate"]["spec"]["containers"][0]["image"]
        == "out-of-band:v2"
    )
    assert store.metadata.get_sandbox(sandbox.record.id) == sandbox.record


def test_two_replicas_coordinate_manual_and_automatic_sync(setup):
    store, kube, sandbox = setup
    drift(kube, sandbox)
    replica, _ = store_for(store.settings, kube)
    entered, release = threading.Event(), threading.Event()
    backend = store.integrations.items["agentSandbox"]
    reconcile = backend.reconcile
    patch = Mock(wraps=kube.patch_namespaced_custom_object)
    kube.patch_namespaced_custom_object = patch

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return reconcile(*args, **kwargs)

    backend.reconcile = blocked
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                store.sync, sandbox.name, OWNER, sandbox.uid, sandbox.record.revision
            )
            assert entered.wait(5)
            try:
                assert replica.reconcile_resources() == []
                with pytest.raises(Conflict, match="already being processed"):
                    replica.sync(
                        sandbox.name, OWNER, sandbox.uid, sandbox.record.revision
                    )
            finally:
                release.set()
            assert not first.result(timeout=5).configuration_drift
        assert replica.reconcile_resources() == []
        patch.assert_called_once()
    finally:
        replica.close()


def test_sync_api_checks_owner_sharing_origin_revision_and_admin_access(setup):
    store, kube, sandbox = setup
    store.sharing(sandbox.name, OWNER, {OTHER: "shell"})
    drift(kube, sandbox)
    settings = replace(store.settings, admin_emails=json.dumps([OTHER]))
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        path = BASE + f"/sandboxes/{sandbox.name}"
        data = browser.get(path + "/configuration", headers=HEADERS).json()
        assert data["can_sync"]
        body = {"uid": data["uid"], "revision": data["revision"]}
        bob = {**HEADERS, "Cookie": "session=bob"}
        shared = browser.get(
            path + "/configuration", headers=bob, params={"owner": OWNER}
        ).json()
        assert not shared["can_sync"]
        assert browser.post(path + "/sync", headers=bob, json=body).status_code == 404
        assert (
            browser.post(
                path + "/sync",
                headers={**HEADERS, "Origin": "https://other.invalid"},
                json=body,
            ).status_code
            == 403
        )
        assert (
            browser.post(
                path + "/sync", headers=HEADERS, json={**body, "revision": 999}
            ).status_code
            == 409
        )
        assert (
            browser.post(
                path + "/sync", headers=HEADERS, json={**body, "manifest": {}}
            ).status_code
            == 422
        )
        assert (
            browser.post(path + "/sync", headers=HEADERS, json=body).status_code == 200
        )
        assert not store.get(sandbox.name, OWNER).configuration_drift
        drift(kube, sandbox)
        admin = BASE + f"/admin/sandboxes/{sandbox.name}/sync?namespace={sandbox.scope}"
        assert browser.post(admin, headers=HEADERS, json=body).status_code == 403
        assert browser.post(admin, headers=bob, json=body).status_code == 200


def test_application_timer_runs_and_stops_before_closing_clients(setup):
    store, kube, sandbox = setup
    drift(kube, sandbox)
    entered, release = threading.Event(), threading.Event()
    backend = store.integrations.items["agentSandbox"]
    observe = backend.observe
    captured = {}
    reconcile = store.reconcile_resources

    def capture(**kwargs):
        captured.update(kwargs)
        return reconcile(**kwargs)

    store.reconcile_resources = capture

    def blocked(binding):
        entered.set()
        assert release.wait(5)
        return observe(binding)

    backend.observe = blocked
    store.close = Mock(wraps=store.close)
    kube.patch_namespaced_custom_object = Mock(
        side_effect=AssertionError("No writes during shutdown")
    )
    client = TestClient(
        create_app(
            replace(store.settings, reconcile_interval_seconds=0.02), store, Omnigent()
        )
    )
    client.__enter__()
    try:
        assert entered.wait(3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            shutdown = pool.submit(client.__exit__, None, None, None)
            try:
                deadline = time.monotonic() + 3
                while not captured["stopping"]() and time.monotonic() < deadline:
                    time.sleep(0.005)
                assert captured["stopping"]()
                assert not shutdown.done()
                store.close.assert_not_called()
            finally:
                release.set()
            shutdown.result(timeout=5)
        kube.patch_namespaced_custom_object.assert_not_called()
        store.close.assert_called_once()
    finally:
        release.set()


def test_future_integrations_opt_in_without_kubernetes_dependencies(remote_store):
    store, backend = remote_store
    sandbox = store.get("calm-fox", OWNER)
    assert not store.configuration(sandbox)["can_sync"]
    assert store.reconcile_resources() == []
    with pytest.raises(HTTPException) as error:
        store.sync(sandbox.name, OWNER, sandbox.uid, sandbox.record.revision)
    assert error.value.status_code == 409
    backend.reconcile = Mock(return_value=True)
    store.sync(sandbox.name, OWNER, sandbox.uid, sandbox.record.revision)
    call = backend.reconcile.call_args
    assert call.args == (sandbox.record.manifest, backend.handle)
    assert callable(call.kwargs["check"])
