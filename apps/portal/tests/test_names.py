import re
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from test_portal import OWNER, SETTINGS
from test_profiles import store_for

from portal.names import ADJECTIVES, ANIMALS, sandbox_name
from portal.profiles import PREFIX
from portal.storage import Conflict


def test_names_fit_both_native_backends_and_preserve_uuid_normalization():
    assert len(ADJECTIVES) == len(set(ADJECTIVES)) == 30
    assert len(ANIMALS) == len(set(ANIMALS)) == 30
    names = {sandbox_name(UUID(int=i)) for i in range(1000)}
    assert len(names) == 1000
    assert {name.split("-")[0] for name in names} == set(ADJECTIVES)
    assert {name.split("-")[1] for name in names} == set(ANIMALS)
    assert max(map(len, ADJECTIVES)) + max(map(len, ANIMALS)) + 7 <= 16
    assert all(len(name) <= 16 for name in names)
    assert all(re.fullmatch(r"[a-z]+-[a-z]+-[0-9a-f]{5}", name) for name in names)
    request = uuid4()
    assert (
        sandbox_name(request) == sandbox_name(str(request)) == sandbox_name(request.hex)
    )


@pytest.mark.parametrize("strategy", ["perUser", "perSandbox"])
def test_saved_friendly_name_is_reused_after_naming_changes(monkeypatch, strategy):
    import json

    settings = replace(SETTINGS, namespace=json.dumps({"strategy": strategy}))
    store, kube = store_for(settings)
    request = uuid4()
    original_name = sandbox_name(request)
    with monkeypatch.context() as previous:
        previous.setattr(
            "portal.integrations.agent_sandbox.inventory.sandbox_name",
            lambda _: original_name,
        )
        retained = store.create(OWNER, "Existing", request).reference
    key = (retained["metadata"]["namespace"], original_name)
    kube.items[key]["metadata"]["annotations"].pop(PREFIX + "request-id")
    before = kube.items[key]

    restarted, _ = store_for(settings, kube)
    retried = restarted.create(OWNER, "Existing", request).reference
    assert retried == before
    assert len(kube.items) == 1
    suspended = restarted.mode(original_name, OWNER, "Suspended").reference
    resumed = restarted.mode(original_name, OWNER, "Running").reference
    assert resumed["metadata"]["uid"] == retained["metadata"]["uid"]
    assert (
        suspended["spec"]["volumeClaimTemplates"]
        == resumed["spec"]["volumeClaimTemplates"]
    )


def test_name_collision_does_not_return_another_creation(monkeypatch):
    store, kube = store_for()
    first = store.create(OWNER).reference
    monkeypatch.setattr(
        "portal.integrations.agent_sandbox.inventory.sandbox_name",
        lambda _: first["metadata"]["name"],
    )
    with pytest.raises(Conflict):
        store.create(OWNER).reference
    assert len(kube.items) == 1


def test_collision_between_validation_and_creation_does_not_return_other_request(
    monkeypatch,
):
    from copy import deepcopy

    from kubernetes.client import ApiException

    store, kube = store_for()
    original = kube.create_namespaced_custom_object

    def create(group, version, namespace, plural, body, dry_run=None, **kwargs):
        if dry_run is not None:
            return original(
                group, version, namespace, plural, body, dry_run=dry_run, **kwargs
            )
        competing = deepcopy(body)
        competing["metadata"]["annotations"][PREFIX + "request-id"] = str(uuid4())
        original(group, version, namespace, plural, competing, **kwargs)
        raise ApiException(409)

    monkeypatch.setattr(kube, "create_namespaced_custom_object", create)
    with pytest.raises(HTTPException) as error:
        store.create(OWNER).reference
    assert error.value.status_code == 409
    assert len(kube.items) == 1
