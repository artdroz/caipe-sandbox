"""Disk choices provision owned native PVCs without weakening request recovery."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from kubernetes.client import ApiException

from portal.integrations.openshell import volumes
from portal.profiles import Profiles
from test_openshell import runtime_class as runtime_class, setup_store
from test_portal import OWNER


def storage_store():
    settings, *_ = setup_store()
    profiles = json.loads(settings.profiles)
    profiles[0]["openShell"]["spec"]["environment"]["HOME"] = "/sandbox/home"
    limits = profiles[0]["ui"]["resources"]
    limits["minimum"]["storage"] = "5Gi"
    limits["maximum"]["storage"] = "100Gi"
    return setup_store(
        openshell_storage_mode="persistentVolumeClaim",
        storage_class="test-encrypted",
        profiles=json.dumps(profiles),
    )


def size(store, disk=32):
    return store.profiles.size(store.profiles.get()).model_copy(
        update={"workspace_gib": disk}
    )


def test_disk_choice_controls_pvc_and_native_attachment():
    settings, store, kube, native = storage_store()
    vm = store.create(OWNER, request_id=uuid4(), size=size(store))
    cr = vm.reference
    (pvc,) = kube.pvcs.values()
    assert pvc["spec"]["resources"]["requests"]["storage"] == "32Gi"
    assert pvc["spec"]["storageClassName"] == "test-encrypted"
    assert pvc["metadata"]["ownerReferences"][0]["uid"] == cr["metadata"]["uid"]
    sandbox = next(iter(native.sandboxes.values()))
    driver = volumes.claim_name(cr)
    assert (
        sandbox.spec.template.driver_config["kubernetes"]["volumes"][0][
            "persistent_volume_claim"
        ]["claim_name"]
        == driver
    )
    mount = sandbox.spec.template.driver_config["kubernetes"]["containers"]["agent"][
        "volume_mounts"
    ][0]
    assert mount["name"] == "portal-workspace"
    assert mount["mount_path"] == "/sandbox/home"
    assert "volumeClaimTemplates" not in cr["spec"]
    assert store.integrations.items["openShell"].allocation(cr).workspace_gib == 32
    assert store.get(str(vm.record.id), OWNER).allocation["workspace_gib"] == 32
    assert vm.record.resource_usage["requests.storage"] == str(32 * 1024**3)
    assert not store.get(str(vm.record.id), OWNER).configuration_drift
    profile = store.profiles.get()
    assert store.profiles.bounds(profile)["workspace_gib"] == {"min": 5, "max": 100}
    assert profile.public(settings)["capabilities"] == {
        "resize": False,
        "storage_source": "profile",
    }


def test_out_of_range_disk_is_rejected_before_any_resources_are_created():
    _, store, kube, native = storage_store()
    with pytest.raises(HTTPException, match="profile resource bounds"):
        store.create(OWNER, request_id=uuid4(), size=size(store, 101))
    assert not kube.pvcs and native.create_calls == 0


def test_pvc_is_reused_after_a_lost_create_response(monkeypatch):
    _, store, kube, native = storage_store()
    nonce = uuid4()
    backend = store.integrations.items["openShell"]
    create = kube.create_namespaced_persistent_volume_claim
    calls = []

    def lost_response(*args, **kwargs):
        pvc = create(*args, **kwargs)
        calls.append(pvc["metadata"]["uid"])
        raise ApiException(503)

    monkeypatch.setattr(
        kube, "create_namespaced_persistent_volume_claim", lost_response
    )
    with pytest.raises(HTTPException):
        store.create(OWNER, request_id=nonce, size=size(store))
    assert len(kube.pvcs) == 1 and native.create_calls == 0
    monkeypatch.setattr(kube, "create_namespaced_persistent_volume_claim", create)
    record = store.metadata.find_creation(OWNER, nonce)
    vm = store.retry(str(record.id), OWNER)
    assert len(kube.pvcs) == 1 and native.create_calls == 1
    assert next(iter(kube.pvcs.values()))["metadata"]["uid"] == calls[0]


def test_foreign_disk_is_never_adopted():
    settings, store, kube, _ = storage_store()
    backend = store.integrations.items["openShell"]
    draft = backend.prepare(OWNER, "test", uuid4(), size(store), store.profiles.get())
    backend.ensure(draft.reference)
    backend.volumes.ensure(draft.reference)
    pvc = next(iter(kube.pvcs.values()))
    pvc["metadata"]["labels"][volumes.PREFIX + "request-id"] = str(uuid4())
    with pytest.raises(HTTPException, match="another allocation"):
        backend.volumes.ensure(draft.reference)
    assert len(kube.pvcs) == 1


def test_lost_gateway_response_recovers_binding_without_creating_another_disk(
    monkeypatch,
):
    _, store, kube, native = storage_store()
    create = native.CreateSandbox
    nonce = uuid4()

    def lose_response(*args, **kwargs):
        create(*args, **kwargs)
        raise HTTPException(504, "Response lost")

    monkeypatch.setattr(native, "CreateSandbox", lose_response)
    with pytest.raises(HTTPException):
        store.create(OWNER, request_id=nonce, size=size(store))
    assert native.create_calls == 1 and len(kube.pvcs) == 1
    assert not next(iter(kube.pvcs.values()))["metadata"].get("ownerReferences")
    record = store.metadata.find_creation(OWNER, nonce)
    vm = store.retry(str(record.id), OWNER)
    assert native.create_calls == 1 and len(kube.pvcs) == 1
    assert (
        next(iter(kube.pvcs.values()))["metadata"]["ownerReferences"][0]["uid"]
        == vm.uid
    )


def test_missing_or_replaced_disk_is_rejected_and_never_recreated():
    _, store, kube, _ = storage_store()
    vm = store.create(OWNER, request_id=uuid4(), size=size(store))
    backend = store.integrations.items["openShell"]
    (key,) = kube.pvcs
    pvc = kube.pvcs.pop(key)
    with pytest.raises(HTTPException, match="disk is missing") as error:
        backend.allocation(vm.reference)
    assert error.value.status_code == 409
    pvc["metadata"]["uid"] = str(uuid4())
    kube.pvcs[key] = pvc
    with pytest.raises(HTTPException, match="another allocation"):
        backend.allocation(vm.reference)


def test_suspend_keeps_disk_and_delete_collects_it():
    _, store, kube, native = storage_store()
    vm = store.create(OWNER, request_id=uuid4(), size=size(store))
    backend = store.integrations.items["openShell"]
    before = deepcopy(kube.pvcs)
    backend.mode(vm.reference, "Suspended")
    backend.mode(vm.reference, "Running")
    assert kube.pvcs == before
    store.delete(str(vm.record.id), OWNER)
    assert not kube.pvcs


def test_cancel_removes_only_an_unbound_disk_after_runtime_absence_is_proven():
    _, store, kube, _ = storage_store()
    backend = store.integrations.items["openShell"]
    draft = backend.prepare(OWNER, "test", uuid4(), size(store), store.profiles.get())
    backend.ensure(draft.reference)
    backend.volumes.ensure(draft.reference)
    with pytest.raises(HTTPException, match="outcome is still unknown"):
        backend.verify_creation_absent(draft.reference, rejected=False)
    assert len(kube.pvcs) == 1
    backend.verify_creation_absent(draft.reference, rejected=True)
    assert not kube.pvcs


def test_gateway_mode_and_existing_native_volumes_remain_supported():
    settings, store, kube, native = setup_store()
    vm = store.create(OWNER, request_id=uuid4())
    assert not kube.pvcs
    assert "volumeClaimTemplates" in vm.reference["spec"]
    assert store.profiles.bounds(store.profiles.get())["workspace_gib"] == {
        "min": 20,
        "max": 20,
    }
    assert (
        store.profiles.get().public(settings)["capabilities"]["storage_source"]
        == "platform"
    )
    with pytest.raises(ValueError, match="storageMode"):
        Profiles(replace(settings, openshell_storage_mode="invalid"))


def test_cancellation_retains_a_disk_still_mounted_by_a_runtime_pod(monkeypatch):
    from types import SimpleNamespace

    _, store, kube, _ = storage_store()
    backend = store.integrations.items["openShell"]
    draft = backend.prepare(OWNER, "test", uuid4(), size(store), store.profiles.get())
    backend.ensure(draft.reference)
    backend.volumes.ensure(draft.reference)
    pod = {
        "metadata": {"name": "shared-supervisor"},
        "spec": {
            "volumes": [
                {
                    "persistentVolumeClaim": {
                        "claimName": volumes.claim_name(draft.reference)
                    }
                }
            ]
        },
    }
    monkeypatch.setattr(
        kube, "list_namespaced_pod", lambda *a, **k: SimpleNamespace(items=[pod])
    )
    with pytest.raises(HTTPException, match="still mounted"):
        backend.verify_creation_absent(draft.reference, rejected=True)
    assert len(kube.pvcs) == 1


@pytest.mark.parametrize(
    "home",
    ["/sandbox", "/tmp/home", "/sandbox/../etc", "/sandbox/home/", "/sandbox//home"],
)
def test_reserved_or_ambiguous_workspace_mounts_are_rejected(home):
    settings, *_ = storage_store()
    profiles = json.loads(settings.profiles)
    profiles[0]["openShell"]["spec"]["environment"]["HOME"] = home
    with pytest.raises(ValueError, match="HOME below /sandbox"):
        Profiles(replace(settings, profiles=json.dumps(profiles)))


def test_disabled_driver_config_has_an_actionable_creation_error():
    from unittest.mock import Mock
    import grpc
    from portal.integrations.errors import CreationRejected
    from portal.integrations.openshell.client import failure

    error = Mock(spec=["code", "details"])
    error.code.return_value = grpc.StatusCode.FAILED_PRECONDITION
    error.details.return_value = (
        "caller driver_config requires allow_driver_config=true"
    )
    result = failure(error, "CreateSandbox")
    assert isinstance(result, CreationRejected)
    assert "selectable workspace disks" in result.detail
    assert "resource admission" in result.detail
