"""Policy intent, authorization, native conflicts and uncertain activation."""

import json
from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from openshell._proto import openshell_pb2 as pb
from test_openshell import runtime_class, setup_store  # noqa: F401
from test_portal import BASE, HEADERS, OTHER, OWNER, Omnigent

from portal.app import IntegrationUpdate, create_app


def test_creation_editor_uses_profile_defaults_and_persists_separate_overrides():
    settings, store, _, native = setup_store()
    profile = store.profiles.get()
    original = deepcopy(profile.openShell.spec["policy"])
    overrides = {
        "openshell": {
            "policy": {
                "filesystem": {
                    **original["filesystem"],
                    "read_write": ["/sandbox", "/tmp/custom"],
                },
                "landlock": {"compatibility": "hard_requirement"},
                "process": {"run_as_user": "sandbox", "run_as_group": "1000"},
            }
        }
    }
    app = create_app(settings, store, Omnigent())
    with TestClient(app) as browser:
        catalog = browser.get(BASE + "/profiles", headers=HEADERS).json()
        descriptor = catalog["profiles"][0]["integrations"][0]
        assert descriptor["id"] == descriptor["icon"] == "openshell"
        assert descriptor["creation"]["policy"] == {
            key: value
            for key, value in original.items()
            if key in {"filesystem", "landlock", "process"}
        }
        nonce = str(uuid4())
        payload = {
            "title": "Custom OpenShell",
            "request_id": nonce,
            "integrations": overrides,
        }
        response = browser.post(BASE + "/sandboxes", headers=HEADERS, json=payload)
        assert response.status_code == 201, response.text
        sandbox = store.creation_request(OWNER, nonce)
        saved = sandbox.record.manifest["spec"]["policy"]
        assert saved["filesystem"]["read_write"] == ["/sandbox", "/tmp/custom"]
        assert saved["process"] == overrides["openshell"]["policy"]["process"]
        assert saved["network_policies"] == original["network_policies"]
        assert (
            sandbox.record.profile_snapshot["definition"]["openShell"]["spec"]["policy"]
            == original
        )
        assert sandbox.record.profile_snapshot["spec"]["policy"] == original
        assert sandbox.record.profile_snapshot["integration_configuration"] == overrides
        assert panel(store, sandbox)["saved_policy"] == saved
        assert (
            browser.post(BASE + "/sandboxes", headers=HEADERS, json=payload).status_code
            == 201
        )
        assert native.create_calls == 1
        altered = deepcopy(payload)
        altered["integrations"]["openshell"]["policy"]["process"]["run_as_user"] = (
            "1234"
        )
        assert (
            browser.post(BASE + "/sandboxes", headers=HEADERS, json=altered).status_code
            == 409
        )
        assert native.create_calls == 1


@pytest.mark.parametrize(
    "configuration",
    [
        {"policy": {"network_policies": {}}},
        {"policy": {"version": 2}},
        {"policy": {"filesystem": None}},
        {"driver_config": {}},
        {"policy": {"process": {"run_as_user": "0"}}},
        {"policy": {"process": {"run_as_user": "1" * 5000}}},
        {"policy": {"process": {"run_as_group": "root"}}},
        {"policy": {"filesystem": {"read_only": ["relative"]}}},
        {"policy": {"filesystem": {"read_write": ["/foo/../etc"]}}},
        {"policy": {"filesystem": {"read_write": ["/"]}}},
        {"policy": {"filesystem": {"read_write": ["//"]}}},
    ],
)
def test_unsafe_or_unrelated_creation_settings_fail_before_native_provisioning(
    configuration,
):
    _, store, kube, native = setup_store()
    with pytest.raises(HTTPException) as error:
        store.create(OWNER, integration_configuration={"openshell": configuration})
    assert error.value.status_code == 422
    assert native.create_calls == 0
    assert not kube.namespace_objects


def test_creation_rejects_unknown_or_unavailable_integrations():
    from test_profiles import store_for

    _, protected, _, native = setup_store()
    direct, _ = store_for()
    for store, key in [(protected, "unknown"), (direct, "openshell")]:
        with pytest.raises(HTTPException) as error:
            store.create(OWNER, integration_configuration={key: {"policy": {}}})
        assert error.value.status_code == 422
    assert native.create_calls == 0


def changed(policy):
    value = deepcopy(policy)
    value["network_policies"]["github"]["endpoints"][0]["host"] = "example.com"
    return value


def panel(store, sandbox):
    return store.integration_panel(
        store.get(str(sandbox.record.id), OWNER), "openshell"
    )


def update(store, sandbox, policy=None, **overrides):
    current = panel(store, sandbox)
    body = IntegrationUpdate(
        uid=current["uid"],
        revision=current["revision"],
        native_revision=current["native_revision"],
        configuration={"policy": policy or changed(current["base_policy"])},
    ).model_copy(update=overrides)
    return store.update_integration(
        store.get(str(sandbox.record.id), OWNER), "openshell", body, OWNER
    )


def test_saved_override_survives_lifecycle_refresh_and_profile_catalog_change():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    original = deepcopy(sandbox.record.profile_snapshot)
    result = update(store, sandbox)
    assert result.record.operation is None
    assert result.record.profile_snapshot == original
    assert panel(store, sandbox)["state"] == "applied"
    assert not result.configuration_drift
    assert (
        result.record.manifest["spec"]["policy"]
        != original["definition"]["openShell"]["spec"]["policy"]
    )
    assert native.calls[-1][0] == "get"
    store.mode(sandbox.name, OWNER, "Suspended")
    store.mode(sandbox.name, OWNER, "Running")
    store.profiles = Mock()
    assert (
        panel(store, sandbox)["saved_policy"]
        == result.record.manifest["spec"]["policy"]
    )
    assert (
        store.configuration(store.get(sandbox.name, OWNER))["desired"]
        == result.record.manifest
    )


@pytest.mark.parametrize(
    "field", ["filesystem", "process", "landlock", "version", "unknown"]
)
def test_static_and_unknown_fields_are_rejected_before_saving(field):
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    value = changed(panel(store, sandbox)["base_policy"])
    value[field] = (
        {"run_as_user": "1234"}
        if field == "process"
        else {}
        if field != "version"
        else 2
    )
    with pytest.raises(HTTPException) as error:
        update(store, sandbox, value)
    assert error.value.status_code == 422
    assert store.metadata.get_sandbox(sandbox.record.id).operation is None
    assert not any(name == "policy" for name, _ in native.calls)


def test_portal_and_native_revision_conflicts():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    with pytest.raises(Exception, match="changed"):
        update(store, sandbox, revision=1)
    with pytest.raises(HTTPException, match="changed"):
        update(store, sandbox, native_revision="999")
    assert not any(name == "policy" for name, _ in native.calls)


def test_revision_request_accepts_provider_owned_opaque_tokens():
    for token in ["policy:2", 'W/"provider-etag"']:
        request = IntegrationUpdate(
            uid="native-id", revision=1, native_revision=token, configuration={}
        )
        assert request.native_revision == token


def test_an_old_sandbox_token_cannot_alias_a_new_policy_version():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    key = (sandbox.scope, sandbox.name)
    old_form = panel(store, sandbox)
    native.sandboxes[key].metadata.resource_version = 2
    old_token = str(native.sandboxes[key].metadata.resource_version)
    revision = native.policies[key]
    revision.version = 2
    revision.policy.network_policies["github"].endpoints[0].host = "other.example.com"
    native.load_policy(key)
    current = panel(store, sandbox)
    assert current["native_revision"] == "policy:2"
    assert old_token == str(current["policy_version"])
    with pytest.raises(HTTPException, match="policy changed"):
        update(
            store, sandbox, changed(old_form["base_policy"]), native_revision=old_token
        )
    assert not any(name == "policy" for name, _ in native.calls)
    assert store.metadata.get_sandbox(sandbox.record.id).operation is None


@pytest.mark.parametrize("stage", ["editing", "planning"])
def test_unrelated_native_updates_keep_policy_edits_valid(stage, monkeypatch):
    from portal.integrations.openshell import policy

    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    key = (sandbox.scope, sandbox.name)
    original = panel(store, sandbox)
    if stage == "editing":
        native.sandboxes[key].metadata.resource_version += 10
    else:
        plan = policy.plan

        def status_update(*args, **kwargs):
            result = plan(*args, **kwargs)
            native.sandboxes[key].metadata.resource_version += 10
            return result

        monkeypatch.setattr(policy, "plan", status_update)
    result = update(store, sandbox, native_revision=original["native_revision"])
    assert result.record.operation is None
    request = next(request for name, request in native.calls if name == "policy")
    assert request.expected_resource_version == 11
    assert not request.request_id
    assert panel(store, sandbox)["state"] == "applied"


@pytest.mark.parametrize("change", ["version", "content"])
def test_policy_change_after_planning_is_never_overwritten(change, monkeypatch):
    from portal.integrations.openshell import policy

    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    key = (sandbox.scope, sandbox.name)
    plan = policy.plan

    def competing_policy(*args, **kwargs):
        result = plan(*args, **kwargs)
        revision = native.policies[key]
        if change == "version":
            revision.version += 1
        revision.policy.network_policies["github"].endpoints[
            0
        ].host = "other.example.com"
        native.sandboxes[key].metadata.resource_version += 1
        native.load_policy(key)
        return result

    monkeypatch.setattr(policy, "plan", competing_policy)
    with pytest.raises(HTTPException, match="outside this operation"):
        update(store, sandbox)
    assert not any(name == "policy" for name, _ in native.calls)
    assert (
        native.policies[key].policy.network_policies["github"].endpoints[0].host
        == "other.example.com"
    )


def test_native_conditional_write_still_rejects_a_last_moment_race():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    key = (sandbox.scope, sandbox.name)
    original = native.UpdateConfig

    def race(request, **kwargs):
        native.sandboxes[key].metadata.resource_version += 1
        return original(request, **kwargs)

    native.UpdateConfig = race
    with pytest.raises(HTTPException, match="Native revision conflict"):
        update(store, sandbox)
    assert native.policies[key].version == 1
    assert (
        store.metadata.get_sandbox(sandbox.record.id).operation.state
        == "needs_attention"
    )


def test_saved_policy_waits_for_activation_without_a_failed_portal_operation():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.auto_load = False
    result = update(store, sandbox)
    assert result.record.operation is None
    assert panel(store, sandbox)["state"] == "applying"
    assert not panel(store, sandbox)["editable"]
    assert not panel(store, sandbox)["pending"]
    with pytest.raises(HTTPException, match="not ready"):
        store.execution(sandbox.name, OWNER)
    native.load_policy((sandbox.scope, sandbox.name))
    assert panel(store, sandbox)["state"] == "applied"
    assert panel(store, sandbox)["editable"]
    assert store.execution(sandbox.name, OWNER)
    assert sum(name == "policy" for name, _ in native.calls) == 1


def test_api_accepts_saved_policy_while_runtime_activation_is_pending():
    settings, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.auto_load = False
    current = panel(store, sandbox)
    body = {key: current[key] for key in ("uid", "revision", "native_revision")}
    body["configuration"] = {"policy": changed(current["base_policy"])}
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        path = BASE + f"/sandboxes/{sandbox.name}/integrations/openshell"
        response = browser.put(path, json=body, headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["operation"] is None
        pending = browser.get(path, headers=HEADERS).json()
        assert pending["state"] == "applying" and not pending["pending"]
        native.load_policy((sandbox.scope, sandbox.name))
        assert browser.get(path, headers=HEADERS).json()["state"] == "applied"
    assert sum(name == "policy" for name, _ in native.calls) == 1


def test_lost_update_response_is_recovered_by_provenance_without_replay():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    original = native.UpdateConfig

    def lost_response(request, **kwargs):
        original(request, **kwargs)
        raise HTTPException(504, "Lost response")

    native.UpdateConfig = lost_response
    with pytest.raises(HTTPException, match="Lost response"):
        update(store, sandbox)
    store.retry(sandbox.name, OWNER)
    assert sum(name == "policy" for name, _ in native.calls) == 1
    assert panel(store, sandbox)["state"] == "applied"


def test_lost_response_retry_confirms_the_save_before_runtime_activation():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.auto_load = False
    original = native.UpdateConfig

    def lost_response(request, **kwargs):
        original(request, **kwargs)
        raise HTTPException(504, "Lost response")

    native.UpdateConfig = lost_response
    with pytest.raises(HTTPException, match="Lost response"):
        update(store, sandbox)
    assert (
        store.metadata.get_sandbox(sandbox.record.id).operation.state
        == "needs_attention"
    )
    assert store.retry(sandbox.name, OWNER).record.operation is None
    assert panel(store, sandbox)["state"] == "applying"
    assert sum(name == "policy" for name, _ in native.calls) == 1


def test_failed_revision_can_be_repaired_without_recreating_runtime():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.auto_load = False
    assert update(store, sandbox).record.operation is None
    revision = native.policies[(sandbox.scope, sandbox.name)]
    revision.status = pb.POLICY_STATUS_FAILED
    revision.load_error = "Conflicting network rule"
    assert panel(store, sandbox)["state"] == "rejected"
    assert panel(store, sandbox)["editable"]
    assert panel(store, sandbox)["detail"] == "Conflicting network rule"
    native.auto_load = True
    repaired = deepcopy(panel(store, sandbox)["base_policy"])
    repaired["network_policies"] = {}
    result = update(store, sandbox, repaired)
    assert result.record.operation is None
    assert native.create_calls == 1
    assert panel(store, sandbox)["state"] == "applied"


def test_loaded_policy_waits_for_native_runtime_admission():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    admission = native.sandboxes[
        (sandbox.scope, sandbox.name)
    ].status.configuration_admission
    admission.state = pb.CONFIGURATION_ADMISSION_STATE_PENDING
    assert panel(store, sandbox)["state"] == "applying"
    assert not panel(store, sandbox)["editable"]
    with pytest.raises(HTTPException, match="not ready"):
        store.execution(sandbox.name, OWNER)
    admission.state = pb.CONFIGURATION_ADMISSION_STATE_ACCEPTED
    assert panel(store, sandbox)["state"] == "applied"


def test_native_admission_rejection_is_an_error_without_a_failed_save():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    assert update(store, sandbox).record.operation is None
    admission = native.sandboxes[
        (sandbox.scope, sandbox.name)
    ].status.configuration_admission
    admission.state = pb.CONFIGURATION_ADMISSION_STATE_REJECTED
    admission.error = "Runtime rejected policy configuration"
    current = panel(store, sandbox)
    assert current["state"] == "rejected"
    assert current["detail"] == admission.error
    assert current["editable"] and not current["pending"]
    row = store.status_view(store.get(sandbox.name, OWNER))
    assert row["state"] == "Error" and row["message"] == admission.error
    assert (
        next(b for b in row["integrations"] if b["id"] == "openshell")["state"]
        == "error"
    )
    with pytest.raises(HTTPException, match="not ready"):
        store.execution(sandbox.name, OWNER)


def test_global_policy_locks_panel_and_prevents_update():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.global_policy = True
    assert not panel(store, sandbox)["editable"]
    with pytest.raises(HTTPException, match="global policy"):
        update(store, sandbox)
    assert not any(name == "policy" for name, _ in native.calls)


def test_out_of_band_revision_is_visible_and_never_overwritten_by_retry():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.auto_load = False
    original = native.UpdateConfig

    def lost_response(request, **kwargs):
        original(request, **kwargs)
        raise HTTPException(504, "Lost response")

    native.UpdateConfig = lost_response
    with pytest.raises(HTTPException, match="Lost response"):
        update(store, sandbox)
    revision = native.policies[(sandbox.scope, sandbox.name)]
    revision.version += 1
    revision.provenance.clear()
    revision.policy.network_policies["github"].endpoints[0].host = "other.example.com"
    native.load_policy((sandbox.scope, sandbox.name))
    assert panel(store, sandbox)["drift"]
    with pytest.raises(HTTPException, match="outside this operation"):
        store.retry(sandbox.name, OWNER)
    assert sum(name == "policy" for name, _ in native.calls) == 1
    assert (
        store.metadata.get_sandbox(sandbox.record.id).manifest["spec"]["policy"][
            "network_policies"
        ]["github"]["endpoints"][0]["host"]
        == "example.com"
    )


def test_shared_shell_access_does_not_grant_policy_editing_and_admin_can_edit():
    settings, store, _, _ = setup_store()
    settings = replace(settings, admin_emails=json.dumps([OTHER]))
    sandbox = store.create(OWNER)
    store.sharing(sandbox.name, OWNER, {OTHER: "shell"})
    current = panel(store, sandbox)
    body = {key: current[key] for key in ("uid", "revision", "native_revision")}
    body["configuration"] = {"policy": changed(current["base_policy"])}
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        path = BASE + f"/sandboxes/{sandbox.name}/integrations/openshell"
        other_headers = {**HEADERS, "Cookie": "session=bob"}
        shared = browser.get(path, params={"owner": OWNER}, headers=other_headers)
        assert shared.status_code == 200
        assert not shared.json()["can_edit"]
        denied = browser.put(path, json=body, headers=other_headers)
        assert denied.status_code == 404
        assert (
            browser.put(path, json=body, headers={"x-user-id": OWNER}).status_code
            == 403
        )
        admin = browser.put(
            BASE + f"/admin/sandboxes/{sandbox.name}/integrations/openshell",
            params={"namespace": sandbox.scope},
            json=body,
            headers=other_headers,
        )
        assert admin.status_code == 200, admin.text


def test_native_network_baseline_does_not_report_drift_or_unknown_activation():
    from portal.integrations.openshell import policy
    from portal.integrations.openshell.client import data

    settings, store, _, native = setup_store()
    definitions = json.loads(settings.profiles)
    definitions[0]["openShell"]["spec"]["policy"]["filesystem"]["read_only"].remove(
        "/var/log"
    )
    from portal.profiles import Profiles

    store.profiles = Profiles(replace(settings, profiles=json.dumps(definitions)))
    sandbox = store.create(OWNER)
    original = deepcopy(sandbox.record.manifest)
    key = (sandbox.scope, sandbox.name)
    revision = native.policies[key]
    revision.policy.filesystem.read_only.append("/var/log")
    revision.version = 2
    native.load_policy(key)
    current = store.get(sandbox.name, OWNER)
    assert not current.configuration_drift
    result = panel(store, current)
    assert result["state"] == "applied"
    assert not result["drift"]
    assert result["policy_version"] == result["active_version"] == 2
    assert "/var/log" in result["effective_policy"]["filesystem"]["read_only"]
    assert store.metadata.get_sandbox(sandbox.record.id).manifest == original
    assert not policy.different(original["spec"]["policy"], data(revision.policy))


@pytest.mark.parametrize(
    "change",
    [
        "unknown-read",
        "unexpected-write",
        "missing-path",
        "network",
        "process",
        "explicit-readonly",
    ],
)
def test_baseline_comparison_keeps_meaningful_policy_changes_visible(change):
    from portal.integrations.openshell import policy

    _, store, _, _ = setup_store()
    saved = deepcopy(store.profiles.get().openShell.spec["policy"])
    current = deepcopy(saved)
    if change == "unknown-read":
        current["filesystem"]["read_only"].append("/private-data")
    elif change == "unexpected-write":
        current["filesystem"]["read_write"].append("/var/log")
    elif change == "missing-path":
        current["filesystem"]["read_only"].remove("/etc")
    elif change == "network":
        current["network_policies"]["github"]["endpoints"][0]["host"] = (
            "other.example.com"
        )
    elif change == "process":
        current["process"] = {"run_as_user": "0"}
    else:
        saved["filesystem"]["read_write"].remove("/tmp")
        saved["filesystem"]["read_only"].append("/tmp")
        current = deepcopy(saved)
        current["filesystem"]["read_write"].append("/tmp")
    assert policy.different(saved, current)


def test_baseline_enrichment_is_not_assumed_without_network_rules():
    from portal.integrations.openshell import policy

    saved = {"version": 1, "filesystem": {"read_only": ["/etc"]}}
    current = deepcopy(saved)
    current["filesystem"]["read_only"].append("/var/log")
    assert policy.different(saved, current)
