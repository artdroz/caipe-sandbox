import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from inventory_fakes import as_sandbox
from kubernetes.client import ApiException
from test_portal import BASE, HEADERS, OWNER, SETTINGS, Kubernetes
from test_portal import setup as portal_setup

from portal.config import runner_pull_secrets
from portal.namespaces import UserNamespaces, namespace_name
from portal.sandboxes import Store

setup = portal_setup


def pod_for(cr, reason=None, phase="Pending", *, init=False):
    state = SimpleNamespace(
        waiting=SimpleNamespace(reason=reason, message="403 Forbidden private-token")
        if reason
        else None,
        terminated=None,
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(
            owner_references=[SimpleNamespace(uid=cr["metadata"]["uid"])]
        ),
        status=SimpleNamespace(
            phase=phase,
            container_statuses=[] if init else [SimpleNamespace(state=state)],
            init_container_statuses=[SimpleNamespace(state=state)] if init else [],
            conditions=[],
        ),
    )


@pytest.mark.parametrize(
    "reason",
    [
        "ErrImagePull",
        "ImagePullBackOff",
        "CrashLoopBackOff",
        "CreateContainerConfigError",
        "InvalidImageName",
        "RunContainerError",
    ],
)
def test_listing_reports_pod_failure_without_raw_messages(setup, reason):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    kube.read_namespaced_pod = Mock(return_value=pod_for(cr, reason))
    response = browser.get(BASE + "/sandboxes", headers=HEADERS)
    row = response.json()["sandboxes"][0]
    assert row["state"] == "Error" and row["reason"] == reason
    assert "private-token" not in response.text
    if reason in {"ErrImagePull", "ImagePullBackOff"}:
        assert "Registry rejected" in row["message"]


def test_crash_loop_overrides_stale_cr_ready_and_recovers(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    cr["status"] = {
        "conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]
    }
    kube.read_namespaced_pod = Mock(
        return_value=pod_for(cr, "CrashLoopBackOff", "Running")
    )
    assert store.status_view(as_sandbox(store, cr))["state"] == "Error"
    kube.read_namespaced_pod.return_value = pod_for(cr, phase="Running")
    assert store.status_view(as_sandbox(store, cr))["state"] == "Running"


def test_pod_creation_failure_is_an_error_and_recovers_when_the_pod_appears(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    cr["status"] = {
        "conditions": [
            {
                "type": "Ready",
                "status": "False",
                "reason": "InvalidConfiguration",
                "message": 'pods "test" is forbidden: admission policy denied request',
                "observedGeneration": cr["metadata"]["generation"],
            }
        ]
    }
    kube.read_namespaced_pod = Mock(side_effect=ApiException(404))
    row = store.status_view(as_sandbox(store, cr))
    assert row["state"] == "Error"
    assert row["reason"] == "InvalidConfiguration"
    assert row["message"] == cr["status"]["conditions"][0]["message"]
    cr["status"]["conditions"][0]["observedGeneration"] -= 1
    assert store.status_view(as_sandbox(store, cr))["state"] == "Provisioning"
    cr["status"]["conditions"] = [
        {
            "type": "Ready",
            "status": "True",
            "observedGeneration": cr["metadata"]["generation"],
        }
    ]
    kube.read_namespaced_pod = Mock(return_value=pod_for(cr, phase="Running"))
    assert store.status_view(as_sandbox(store, cr))["state"] == "Running"


def test_init_container_and_exit_failures(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    pod = pod_for(cr, "CreateContainerConfigError", init=True)
    kube.read_namespaced_pod = Mock(return_value=pod)
    assert (
        store.status_view(as_sandbox(store, cr))["reason"]
        == "CreateContainerConfigError"
    )
    pod.status.init_container_statuses = []
    pod.status.container_statuses = [
        SimpleNamespace(
            state=SimpleNamespace(waiting=None, terminated=SimpleNamespace(exit_code=2))
        )
    ]
    assert store.status_view(as_sandbox(store, cr))["reason"] == "ContainerExited"
    assert "code 2" in store.status_view(as_sandbox(store, cr))["message"]
    pod.status.container_statuses = []
    pod.status.phase = "Failed"
    assert store.status_view(as_sandbox(store, cr))["reason"] == "PodFailed"


def test_missing_foreign_and_suspended_pods_do_not_supply_errors(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    kube.read_namespaced_pod = Mock(side_effect=ApiException(404))
    assert store.status_view(as_sandbox(store, cr))["state"] == "Provisioning"
    pod = pod_for(cr, "ErrImagePull")
    pod.metadata.owner_references[0].uid = "another-sandbox"
    kube.read_namespaced_pod = Mock(return_value=pod)
    assert store.status_view(as_sandbox(store, cr))["state"] == "Provisioning"
    cr["spec"]["operatingMode"] = "Suspended"
    kube.read_namespaced_pod.reset_mock()
    assert store.status_view(as_sandbox(store, cr))["state"] == "Suspending"
    kube.read_namespaced_pod.assert_not_called()


def test_status_read_failure_does_not_expose_kubernetes_error(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    kube.read_namespaced_pod = Mock(
        side_effect=ApiException(403, reason="private-token")
    )
    row = store.status_view(as_sandbox(store, cr))
    assert row["message"] == "Pod status temporarily unavailable"
    assert "private-token" not in json.dumps(row)


def test_scheduling_delay_is_not_a_failure(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    pod = pod_for(cr)
    pod.status.conditions = [SimpleNamespace(type="PodScheduled", status="False")]
    kube.read_namespaced_pod = Mock(return_value=pod)
    row = store.status_view(as_sandbox(store, cr))
    assert row["state"] == "Provisioning" and "node capacity" in row["message"]


def test_unauthorized_listing_does_not_read_other_users_pods(setup):
    browser, store, kube, _ = setup
    store.create(OWNER).reference
    kube.read_namespaced_pod = Mock()
    browser.get(BASE + "/sandboxes?owner=" + OWNER, headers={"Cookie": "session=bob"})
    kube.read_namespaced_pod.assert_not_called()


def test_configured_registry_labels_and_runner_pull_references_on_create_resume():
    policy = json.loads(SETTINGS.namespace_policy)
    policy["labels"] = {
        "imps": "true",
    }
    settings = replace(
        SETTINGS,
        namespace_policy=json.dumps(policy),
        runner_image_pull_secrets='[{"name":"regcred"}]',
    )
    kube = Kubernetes()
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    cr = store.create(OWNER).reference
    ns = kube.namespace_objects[namespace_name(settings, OWNER)]
    assert ns["metadata"]["labels"]["imps"] == "true"
    assert ns["metadata"]["labels"]["app.kubernetes.io/name"] == "agent-sandbox-portal"
    assert cr["spec"]["podTemplate"]["spec"]["imagePullSecrets"] == [
        {"name": "regcred"}
    ]
    store.mode(cr["metadata"]["name"], OWNER, "Suspended").reference
    store.settings = replace(settings, runner_image_pull_secrets='[{"name":"newcred"}]')
    resumed = store.mode(cr["metadata"]["name"], OWNER, "Running").reference
    assert resumed["spec"]["podTemplate"]["spec"]["imagePullSecrets"] == [
        {"name": "regcred"}
    ]
    assert (
        resumed["spec"]["podTemplate"]["spec"]["automountServiceAccountToken"] is False
    )


@pytest.mark.parametrize(
    "value",
    ["{}", '["regcred"]', '[{"name":""}]', '[{"name":"regcred","token":"secret"}]'],
)
def test_pull_secret_configuration_accepts_only_name_references(value):
    with pytest.raises(ValueError):
        runner_pull_secrets(replace(SETTINGS, runner_image_pull_secrets=value))


class CleanupKubernetes(Kubernetes):
    def create_namespace(self, body):
        super().create_namespace(body)
        self.namespace_objects[body["metadata"]["name"]]["metadata"].update(
            uid="namespace-uid", resourceVersion="1"
        )

    def delete_namespace(self, name, body):
        assert body["preconditions"] == {"uid": "namespace-uid", "resourceVersion": "1"}
        del self.namespace_objects[name]
        self.baseline = {k: v for k, v in self.baseline.items() if k[1] != name}


def cleanup_store(enabled=True, **overrides):
    policy = json.loads(SETTINGS.namespace_policy)
    policy["deleteWhenEmpty"] = enabled
    settings = replace(SETTINGS, namespace_policy=json.dumps(policy), **overrides)
    kube = CleanupKubernetes()
    return Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    ), kube


def test_namespace_cleanup_only_after_final_sandbox():
    store, kube = cleanup_store()
    first, second = store.create(OWNER).reference, store.create(OWNER).reference
    namespace = first["metadata"]["namespace"]
    assert store.delete(first["metadata"]["name"], OWNER)["status"] == "deleting"
    store.cleanup_namespaces()
    assert namespace in kube.namespace_objects
    assert store.delete(second["metadata"]["name"], OWNER)["status"] == "deleting"
    store.cleanup_namespaces()
    assert namespace not in kube.namespace_objects
    recreated = store.create(OWNER).reference
    assert recreated["metadata"]["namespace"] == namespace


def test_namespace_cleanup_disabled_and_foreign_sandbox_are_preserved():
    store, kube = cleanup_store(False)
    cr = store.create(OWNER).reference
    store.delete(cr["metadata"]["name"], OWNER)
    assert cr["metadata"]["namespace"] in kube.namespace_objects
    store, kube = cleanup_store()
    cr, foreign = store.create(OWNER).reference, store.create(OWNER).reference
    metadata = kube.items[
        (foreign["metadata"]["namespace"], foreign["metadata"]["name"])
    ]["metadata"]
    metadata["labels"]["app.kubernetes.io/name"] = "another-app"
    metadata["deletionTimestamp"] = "2026-10-09T17:00:00Z"
    store.delete(cr["metadata"]["name"], OWNER)
    assert cr["metadata"]["namespace"] in kube.namespace_objects


@pytest.mark.parametrize(
    ("secret_name", "secret_type", "cleaned"),
    [
        ("regcred", "kubernetes.io/dockerconfigjson", True),
        ("regcred", "kubernetes.io/dockercfg", True),
        ("regcred", "Opaque", False),
        ("user-credentials", "Opaque", False),
        ("other-registry", "kubernetes.io/dockerconfigjson", False),
    ],
)
def test_namespace_cleanup_ignores_only_configured_registry_secrets(
    secret_name, secret_type, cleaned
):
    store, kube = cleanup_store(runner_image_pull_secrets='[{"name":"regcred"}]')
    sandbox = store.create(OWNER)
    kube.secrets[secret_name] = SimpleNamespace(
        metadata=SimpleNamespace(name=secret_name, namespace=sandbox.scope),
        type=secret_type,
    )
    store.delete(sandbox.name, OWNER)
    store.cleanup_namespaces()
    assert (sandbox.scope not in kube.namespace_objects) is cleaned


def test_cleanup_failure_is_reported_after_sandbox_delete():
    store, kube = cleanup_store()
    cr = store.create(OWNER).reference
    kube.delete_namespace = Mock(side_effect=ApiException(403, reason="secret-token"))
    result = store.delete(cr["metadata"]["name"], OWNER)
    assert result == {"status": "deleting"}
    with pytest.raises(ApiException):
        store.cleanup_namespaces()
    assert not kube.items
    assert cr["metadata"]["namespace"] in kube.namespace_objects


def test_create_on_another_replica_retries_after_scope_cleanup():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    store, kube = cleanup_store()
    replica = Store(
        store.settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(store.settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    cr = store.create(OWNER).reference
    deleting, release = threading.Event(), threading.Event()
    delete_namespace = kube.delete_namespace

    def blocked_delete(name, body):
        deleting.set()
        assert release.wait(2)
        delete_namespace(name, body)

    kube.delete_namespace = blocked_delete
    with ThreadPoolExecutor(2) as threads:
        store.delete(cr["metadata"]["name"], OWNER)
        deletion = threads.submit(store.cleanup_namespaces)
        assert deleting.wait(2)
        from uuid import uuid4

        from portal.storage import Conflict

        request_id = uuid4()
        try:
            with pytest.raises(Conflict, match="already being processed"):
                replica.create(OWNER, request_id=request_id)
        finally:
            release.set()
        assert deletion.result() is None
        created = replica.create(OWNER, request_id=request_id).reference
    assert (created["metadata"]["namespace"], created["metadata"]["name"]) in kube.items


def test_unresolved_create_preserves_empty_namespace(monkeypatch):
    store, kube = cleanup_store()
    first = store.create(OWNER)
    namespace = first.scope
    backend = store.integrations.items["agentSandbox"]
    monkeypatch.setattr(backend, "create", Mock(side_effect=OSError("connection lost")))
    with pytest.raises(OSError):
        store.create(OWNER)
    store.delete(first.name, OWNER)
    store.cleanup_namespaces()
    assert not kube.items and namespace in kube.namespace_objects


def test_active_scope_claim_skips_namespace_cleanup():
    store, kube = cleanup_store()
    sandbox = store.create(OWNER)
    store.delete(sandbox.name, OWNER)
    backend = store.integrations.items["agentSandbox"]
    with store.scope_operation(backend, sandbox.scope):
        store.cleanup_namespaces()
        assert sandbox.scope in kube.namespace_objects
    store.cleanup_namespaces()
    assert sandbox.scope not in kube.namespace_objects


def test_terminating_namespace_lists_empty_and_create_waits():
    from fastapi import HTTPException

    store, kube = cleanup_store()
    cr = store.create(OWNER).reference
    kube.namespace_objects[cr["metadata"]["namespace"]]["metadata"][
        "deletionTimestamp"
    ] = "2026-10-09T17:00:00Z"
    assert len(store.list(OWNER)) == 1  # Native state cannot erase a saved reservation.
    with pytest.raises(HTTPException) as exc:
        store.create(OWNER).reference
    assert exc.value.status_code == 409 and "cleanup" in exc.value.detail
