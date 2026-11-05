import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, OTHER, OWNER, SETTINGS, Omnigent
from test_profiles import store_for
from test_provisioning import CleanupKubernetes

from portal.app import create_app
from portal.controls import GlobalUpdate, NamespaceUpdate
from portal.storage import scope_key

BOB = {"Origin": SETTINGS.origin, "Cookie": "session=bob"}


@pytest.fixture
def namespace_setup():
    settings = replace(
        SETTINGS,
        namespace='{"strategy":"perSandbox","allowedStrategies":["perSandbox","perUser"]}',
        admin_emails=json.dumps([OWNER]),
    )
    store, kube = store_for(settings, CleanupKubernetes())
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        yield browser, store, kube


def set_lock(browser, sandbox, locked):
    inventory = browser.get(BASE + "/admin/sandboxes", headers=HEADERS).json()
    row = next(
        row
        for row in inventory["sandboxes"]
        if row["portal_id"] == str(sandbox.record.id)
    )
    response = browser.put(
        BASE + "/admin/namespaces/" + row["namespace_key"],
        headers=HEADERS,
        json={
            "resource_version": inventory["controls"]["resource_version"],
            "locked": locked,
        },
    )
    assert response.status_code == 200, response.text
    return row, inventory["controls"]["resource_version"]


def test_unlocked_namespace_reuse_requires_ownership_or_shell_sharing(namespace_setup):
    browser, store, kube = namespace_setup
    first = store.create(OWNER)
    for members in ({}, {OTHER: "view"}):
        store.sharing(first.name, OWNER, members)
        assert browser.get(BASE + "/namespaces", headers=BOB).json()["namespaces"] == []
        assert (
            browser.post(
                BASE + "/sandboxes", headers=BOB, json={"namespace": first.scope}
            ).status_code
            == 403
        )
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    choices = browser.get(BASE + "/namespaces", headers=BOB).json()["namespaces"]
    assert [row["name"] for row in choices] == [first.scope]
    second = browser.post(
        BASE + "/sandboxes",
        headers=BOB,
        json={"title": "Bob micro VM", "namespace": first.scope},
    )
    assert second.status_code == 201, second.text
    second = second.json()
    assert second["namespace_owner"] == OWNER and second["owner"] == OTHER
    assert second["namespace"] == first.scope
    assert (
        kube.namespace_objects[first.scope]["metadata"]["annotations"][
            "sandbox.caipe.io/owner"
        ]
        == OWNER
    )
    mine = browser.get(BASE + "/sandboxes", headers=BOB).json()["sandboxes"]
    assert [row["id"] for row in mine] == [second["id"]]
    assert mine[0]["can_manage"] and mine[0]["can_shell"] and not mine[0]["can_share"]
    alice = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"]
    bob_row = next(row for row in alice if row["owner"] == OTHER)
    assert not bob_row["can_manage"] and bob_row["can_shell"] and bob_row["can_share"]
    path = BASE + "/sandboxes/" + second["portal_id"]
    assert browser.post(path + "/suspend", headers=HEADERS).status_code == 404
    assert browser.post(path + "/suspend", headers=BOB).status_code == 200
    assert (
        browser.put(
            path + "/sharing", headers=BOB, json={"members": {OWNER: "view"}}
        ).status_code
        == 403
    )
    assert (
        browser.put(
            path + "/sharing", headers=HEADERS, json={"members": {OTHER: "view"}}
        ).status_code
        == 200
    )
    assert browser.get(BASE + "/namespaces", headers=BOB).json()["namespaces"] == []
    assert (
        browser.post(
            BASE + "/sandboxes", headers=BOB, json={"namespace": first.scope}
        ).status_code
        == 403
    )
    assert browser.get(path + "/configuration", headers=BOB).status_code == 200
    browser.delete(BASE + "/sandboxes/" + str(first.record.id), headers=HEADERS)
    store.admin_list()
    assert store.get(second["id"], OTHER).record.scope_owner == OWNER


def test_lock_blocks_owner_and_collaborators_without_stopping_existing_vms(
    namespace_setup,
):
    browser, store, _ = namespace_setup
    first = store.create(OWNER)
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    before = store.get(first.name, OWNER)
    row, old_version = set_lock(browser, first, True)
    for headers in (HEADERS, BOB):
        assert (
            browser.get(BASE + "/namespaces", headers=headers).json()["namespaces"]
            == []
        )
        assert (
            browser.post(
                BASE + "/sandboxes", headers=headers, json={"namespace": first.scope}
            ).status_code
            == 403
        )
    assert store.get(first.name, OWNER).state == before.state
    inventory = browser.get(BASE + "/admin/sandboxes", headers=HEADERS).json()
    assert inventory["sandboxes"][0]["namespace_locked"]
    path = BASE + "/sandboxes/" + str(first.record.id)
    assert browser.post(path + "/suspend", headers=HEADERS).status_code == 200
    assert browser.post(path + "/resume", headers=HEADERS).status_code == 200
    lock_path = BASE + "/admin/namespaces/" + row["namespace_key"]
    assert (
        browser.put(
            lock_path,
            headers=HEADERS,
            json={"resource_version": old_version, "locked": False},
        ).status_code
        == 409
    )
    assert (
        browser.put(
            lock_path,
            headers=BOB,
            json={
                "resource_version": inventory["controls"]["resource_version"],
                "locked": False,
            },
        ).status_code
        == 403
    )
    assert (
        browser.put(
            lock_path,
            headers=HEADERS,
            json={
                "resource_version": inventory["controls"]["resource_version"],
                "locked": False,
                "creators": [OTHER],
            },
        ).status_code
        == 422
    )
    set_lock(browser, first, False)
    assert (
        browser.post(
            BASE + "/sandboxes", headers=BOB, json={"namespace": first.scope}
        ).status_code
        == 201
    )


def test_namespace_uid_change_is_not_adopted(namespace_setup):
    browser, store, kube = namespace_setup
    first = store.create(OWNER)
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    backend = store.integrations.items["agentSandbox"]
    create = backend.create

    def changed_namespace(body, request_id):
        kube.namespace_objects[first.scope]["metadata"]["uid"] = "replacement-namespace"
        return create(body, request_id)

    backend.create = changed_namespace
    result = browser.post(
        BASE + "/sandboxes", headers=BOB, json={"namespace": first.scope}
    )
    assert result.status_code == 409 and "Namespace changed" in result.text
    assert len(kube.items) == 1


def test_global_control_saves_preserve_namespace_locks(namespace_setup):
    browser, store, _ = namespace_setup
    first = store.create(OWNER)
    set_lock(browser, first, True)
    policy, version = store.controls.read()
    store.controls.save(
        GlobalUpdate(
            resource_version=version,
            creation_disabled=False,
            sandboxes_disabled=False,
            reason="",
        ),
        OWNER,
    )
    assert store.controls.read()[0].namespaces == policy.namespaces


def test_locked_namespace_is_cleaned_up_after_its_last_vm():
    settings = replace(
        SETTINGS,
        namespace='{"strategy":"perSandbox","allowedStrategies":["perSandbox","perUser"]}',
        namespace_policy=json.dumps(
            {**json.loads(SETTINGS.namespace_policy), "deleteWhenEmpty": True}
        ),
    )
    store, kube = store_for(settings, CleanupKubernetes())
    first = store.create(OWNER)
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    second = store.create(OTHER, namespace=first.scope)
    store.namespace_access.save(
        scope_key(first.provider, first.record.provider_instance, first.scope),
        NamespaceUpdate(resource_version=store.controls.read()[1], locked=True),
        OWNER,
    )
    store.delete(first.name, OWNER)
    store.cleanup_namespaces()
    assert first.scope in kube.namespace_objects
    assert store.get(second.name, OTHER).record.scope_owner == OWNER
    store.delete(second.name, OTHER)
    store.cleanup_namespaces()
    assert first.scope not in kube.namespace_objects
    assert not store.controls.read()[0].namespaces


def test_portal_ids_distinguish_matching_friendly_names_across_creators(
    namespace_setup,
):
    browser, store, _ = namespace_setup
    nonce = uuid4()
    first = store.create(OWNER, request_id=nonce)
    target = store.create(OWNER)
    store.sharing(target.name, OWNER, {OTHER: "shell"})
    second = store.create(OTHER, request_id=nonce, namespace=target.scope)
    assert first.name == second.name and first.scope != second.scope
    first_path = BASE + "/sandboxes/" + str(first.record.id)
    second_path = BASE + "/sandboxes/" + str(second.record.id)
    assert (
        browser.get(first_path + "/configuration", headers=HEADERS).json()["namespace"]
        == first.scope
    )
    assert (
        browser.get(second_path + "/configuration", headers=HEADERS).json()["namespace"]
        == second.scope
    )
    assert browser.post(second_path + "/suspend", headers=HEADERS).status_code == 404
    assert browser.post(second_path + "/suspend", headers=BOB).status_code == 200
