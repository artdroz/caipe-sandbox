"""Admin-only namespace policies, durable intent and safe native boundaries."""

from copy import deepcopy
import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from kubernetes.client import ApiException
from test_profiles import store_for
from test_portal import BASE, HEADERS, OWNER, Omnigent
from test_openshell import setup_store, runtime_class  # noqa: F401

from portal.app import IntegrationUpdate, create_app
from portal.controls import NamespaceUpdate
from portal.integrations.kubernetes import policy as kubernetes
from portal.storage import Conflict, scope_key


def request(store, sandbox):
    current = store.integration_panel(sandbox, "kubernetes")
    candidate = deepcopy(current["policy"])
    candidate["spec"]["egress"] = [
        {
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "team-services"}
                    },
                    "podSelector": {"matchLabels": {"app": "api"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8443}],
        }
    ]
    return IntegrationUpdate(
        uid=current["uid"],
        revision=current["revision"],
        native_revision=current["native_revision"],
        configuration={"policy": candidate},
    )


def test_creator_can_view_but_only_admin_can_write_through_both_routes():
    store, kube = store_for()
    sandbox = store.create(OWNER)
    app = create_app(store.settings, store, Omnigent())
    with TestClient(app) as browser:
        url = BASE + f"/sandboxes/{sandbox.name}/integrations/kubernetes"
        assert browser.get(url, headers=HEADERS).json()["can_edit"] is False
        payload = request(store, sandbox).model_dump()
        assert browser.put(url, headers=HEADERS, json=payload).status_code == 403
        admin_url = (
            BASE
            + f"/admin/sandboxes/{sandbox.name}/integrations/kubernetes?namespace={sandbox.scope}"
        )
        assert browser.put(admin_url, headers=HEADERS, json=payload).status_code == 403
    with pytest.raises(HTTPException) as error:
        store.update_integration(sandbox, "kubernetes", request(store, sandbox), OWNER)
    assert error.value.status_code == 403
    assert ("NetworkPolicy", sandbox.scope, kubernetes.NAME) not in kube.baseline


def test_admin_write_persists_once_per_namespace_and_preserves_lock():
    store, kube = store_for()
    sandbox = store.create(OWNER)
    original = deepcopy(kube.baseline)
    update = request(store, sandbox)
    store.update_integration(sandbox, "kubernetes", update, OWNER, admin=True)
    current = store.integration_panel(sandbox, "kubernetes")
    assert not current["drift"]
    assert current["policy"]["spec"]["egress"][0]["ports"][0]["port"] == 8443
    assert all(kube.baseline[key] == value for key, value in original.items())
    key = scope_key(sandbox.provider, sandbox.record.provider_instance, sandbox.scope)
    _, revision = store.controls.read()
    store.namespace_access.save(
        key, NamespaceUpdate(resource_version=revision, locked=True), OWNER
    )
    control = store.controls.read()[0].namespaces[key]
    assert control.creation_disabled
    assert control.network_policy["updated_by"] == OWNER
    with pytest.raises(Conflict, match="Namespace policies changed"):
        store.update_integration(sandbox, "kubernetes", update, OWNER, admin=True)


def test_admin_can_write_via_own_and_admin_api_and_other_users_remain_read_only():
    store, _ = store_for()
    sandbox = store.create(OWNER)
    settings = replace(store.settings, admin_emails=json.dumps([OWNER]))
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        path = BASE + f"/sandboxes/{sandbox.name}/integrations/kubernetes"
        assert browser.get(path, headers=HEADERS).json()["can_edit"]
        result = browser.put(
            path, headers=HEADERS, json=request(store, sandbox).model_dump()
        )
        assert result.status_code == 200, result.text
        path = (
            BASE
            + f"/admin/sandboxes/{sandbox.name}/integrations/kubernetes?namespace={sandbox.scope}"
        )
        result = browser.put(
            path, headers=HEADERS, json=request(store, sandbox).model_dump()
        )
        assert result.status_code == 200, result.text


@pytest.mark.parametrize(
    "field",
    ["identity", "namespace_uid", "owner_reference", "selector", "ingress", "type"],
)
def test_native_json_cannot_retarget_or_replace_runtime_policy(field):
    store, _ = store_for()
    sandbox = store.create(OWNER)
    update = request(store, sandbox)
    policy = update.configuration["policy"]
    if field == "identity":
        policy["metadata"]["name"] = "sandbox-isolation"
    elif field == "namespace_uid":
        policy["metadata"]["annotations"]["sandbox.caipe.io/namespace-uid"] = (
            "other-namespace"
        )
    elif field == "owner_reference":
        policy["metadata"]["ownerReferences"][0]["uid"] = "other-namespace"
    elif field == "selector":
        policy["spec"]["podSelector"] = {"matchLabels": {"other": "pod"}}
    elif field == "ingress":
        policy["spec"]["ingress"] = [{}]
    else:
        policy["spec"]["policyTypes"] = ["Ingress", "Egress"]
    with pytest.raises(HTTPException) as error:
        store.update_integration(sandbox, "kubernetes", update, OWNER, admin=True)
    assert error.value.status_code == 422


def test_open_shell_policy_selects_only_supervisors_without_gateway_dependency():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.GetSandbox = Mock(
        side_effect=AssertionError("NetworkPolicy reads must not use the gateway")
    )
    current = store.integration_panel(sandbox, "kubernetes")
    assert current["policy"]["spec"]["podSelector"] == {
        "matchLabels": {"openshell.ai/component": "supervisor"}
    }
    assert current["policy"]["spec"]["policyTypes"] == ["Egress"]


def test_strict_dry_run_failure_never_saves_intent():
    store, kube = store_for()
    sandbox = store.create(OWNER)
    update = request(store, sandbox)
    revision = store.controls.read()[1]
    kube.create_namespaced_network_policy = Mock(side_effect=ApiException(422))
    with pytest.raises(HTTPException, match="Kubernetes rejected"):
        store.update_integration(sandbox, "kubernetes", update, OWNER, admin=True)
    assert store.controls.read()[1] == revision


def test_two_micro_vms_cannot_overwrite_each_others_namespace_policy_draft():
    store, _ = store_for()
    first, second = store.create(OWNER), store.create(OWNER)
    assert first.scope == second.scope
    first_draft, second_draft = request(store, first), request(store, second)
    store.update_integration(first, "kubernetes", first_draft, OWNER, admin=True)
    with pytest.raises(Conflict, match="Namespace policies changed"):
        store.update_integration(second, "kubernetes", second_draft, OWNER, admin=True)
    assert store.integration_panel(second, "kubernetes")["scope_count"] == 2


def test_foreign_connection_policy_is_never_adopted():
    store, kube = store_for()
    sandbox = store.create(OWNER)
    current = store.integration_panel(sandbox, "kubernetes")
    foreign = deepcopy(current["policy"])
    foreign["metadata"]["labels"] = {"app.kubernetes.io/name": "another-controller"}
    kube.create_namespaced_network_policy(sandbox.scope, foreign)
    with pytest.raises(HTTPException, match="another controller"):
        store.integration_panel(sandbox, "kubernetes")


def test_failed_native_write_keeps_intent_for_reconciliation_and_rejects_reused_namespace():
    store, kube = store_for()
    sandbox = store.create(OWNER)
    update = request(store, sandbox)
    create = kube.create_namespaced_network_policy
    kube.create_namespaced_network_policy = Mock(
        side_effect=lambda *a, **kw: create(*a, **kw)
        if kw.get("dry_run")
        else (_ for _ in ()).throw(ApiException(503))
    )
    with pytest.raises(HTTPException, match="did not confirm"):
        store.update_integration(sandbox, "kubernetes", update, OWNER, admin=True)
    assert store.integration_panel(sandbox, "kubernetes")["drift"]
    kube.create_namespaced_network_policy = create
    kubernetes.reconcile_scope(store._backend(sandbox.record), sandbox.record)
    assert not store.integration_panel(sandbox, "kubernetes")["drift"]
    kube.namespace_objects[sandbox.scope]["metadata"]["uid"] = "replacement-namespace"
    with pytest.raises(HTTPException, match="Namespace identity changed"):
        kubernetes.reconcile_scope(store._backend(sandbox.record), sandbox.record)
