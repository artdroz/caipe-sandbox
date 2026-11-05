import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from inventory_fakes import as_sandbox
from kubernetes.client import ApiException
from starlette.websockets import WebSocketDisconnect
from test_admin import AdminKubernetes
from test_portal import BASE, HEADERS, OTHER, OWNER, SETTINGS, Omnigent

from portal.app import create_app
from portal.controls import GlobalUpdate, SandboxUpdate, sandbox_control
from portal.integrations.agent_sandbox import execution
from portal.integrations.agent_sandbox.inventory import PREFIX
from portal.namespaces import UserNamespaces
from portal.sandboxes import Store
from portal.storage import StorageError
from portal.storage.schema import controls

BOB = {"Origin": SETTINGS.origin, "Cookie": "session=bob"}


@pytest.fixture
def setup():
    settings = replace(SETTINGS, admin_emails=json.dumps([OWNER]))
    kube = AdminKubernetes()
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        yield browser, store, kube, settings


def target(cr):
    meta = cr["metadata"]
    return (
        BASE
        + f"/admin/sandboxes/{meta['name']}/control?namespace={meta['namespace']}&uid={meta['uid']}"
    )


def global_body(browser, **changes):
    previous = browser.get(BASE + "/admin/sandboxes", headers=HEADERS).json()[
        "controls"
    ]
    notice = previous["announcement"] or {"title": "", "body": ""}
    return {
        "resource_version": previous["resource_version"],
        "creation_disabled": previous["creation_disabled"],
        "sandboxes_disabled": previous["sandboxes_disabled"],
        "reason": previous["reason"],
        "users": previous["users"],
        "announcement": {key: notice[key] for key in ("title", "body")},
        **changes,
    }


def test_disable_is_in_database_suspends_blocks_user_actions_and_survives_restart(
    setup,
):
    browser, store, kube, settings = setup
    cr = store.create(OTHER).reference
    name = cr["metadata"]["name"]
    result = browser.put(
        target(cr),
        headers=HEADERS,
        json={
            "resource_version": "2",
            "disabled": True,
            "reason": "Maintenance",
            "notice": {
                "title": "Workspace maintenance",
                "body": "Contact platform before resuming.",
            },
        },
    )
    assert result.status_code == 200
    record = store.get(name, OTHER).reference
    assert record["spec"]["operatingMode"] == "Suspended"
    control = store.get(name, OTHER).record.control
    assert PREFIX + "admin-control" not in record["metadata"]["annotations"]
    assert control["disabled"] and control["notice"]["author"] == OWNER
    row = browser.get(BASE + "/sandboxes", headers=BOB).json()["sandboxes"][0]
    assert row["disabled"] and not row["can_manage"] and not row["can_shell"]
    assert row["admin_control"]["notice"]["body"] == "Contact platform before resuming."
    for suffix, method, body in [
        ("resume", "post", None),
        ("suspend", "post", None),
        ("sharing", "put", {"members": {}}),
        ("resources", "put", row["allocation"]),
        ("", "delete", None),
    ]:
        response = getattr(browser, method)(
            BASE + f"/sandboxes/{name}" + ("/" + suffix if suffix else ""),
            headers=BOB,
            **({"json": body} if body else {}),
        )
        assert response.status_code == 403, response.text
    assert (
        browser.get(BASE + f"/sandboxes/{name}/tools", headers=BOB).status_code == 403
    )
    with browser.websocket_connect(
        BASE + f"/sandboxes/{name}/terminal", headers=BOB
    ) as ws:
        assert ws.receive_json(mode="binary")["code"] == "http-403"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    restored = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=store.integrations.catalog.namespaces,
        metadata=kube.metadata,
    )
    with pytest.raises(HTTPException) as error:
        restored.check_access(as_sandbox(restored, record))
    assert error.value.status_code == 403
    enabled = browser.put(
        target(record),
        headers=HEADERS,
        json={
            "resource_version": as_sandbox(store, record).resource_version,
            "disabled": False,
        },
    )
    assert enabled.status_code == 200
    assert store.get(name, OTHER).reference["spec"]["operatingMode"] == "Suspended"


def test_shared_users_cannot_bypass_disabled_sandbox(setup):
    browser, store, _, _ = setup
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    store.sharing(name, OWNER, {OTHER: "shell"}).reference
    cr = store.get(name, OWNER).reference
    browser.put(
        target(cr),
        headers=HEADERS,
        json={
            "resource_version": as_sandbox(store, cr).resource_version,
            "disabled": True,
        },
    )
    response = browser.get(BASE + f"/sandboxes/{name}/tools?owner={OWNER}", headers=BOB)
    assert response.status_code == 403
    row = browser.get(BASE + f"/sandboxes?owner={OWNER}", headers=BOB).json()[
        "sandboxes"
    ][0]
    assert row["disabled"] and not row["can_shell"]


def test_global_creation_and_targeted_creation_restrictions_are_independent(setup):
    browser, _store, kube, _ = setup
    response = browser.put(
        BASE + "/admin/controls",
        headers=HEADERS,
        json=global_body(
            browser,
            users={OTHER: {"creation_disabled": True, "reason": "Quota review"}},
        ),
    )
    assert response.status_code == 200
    assert browser.post(BASE + "/sandboxes", headers=BOB).status_code == 403
    assert browser.post(BASE + "/sandboxes", headers=HEADERS).status_code == 201
    payload = global_body(browser, creation_disabled=True, reason="Cluster maintenance")
    assert (
        browser.put(BASE + "/admin/controls", headers=HEADERS, json=payload).status_code
        == 200
    )
    assert browser.post(BASE + "/sandboxes", headers=HEADERS).status_code == 403
    assert (
        browser.get(BASE + "/sandboxes", headers=BOB).json()["creation_disabled_reason"]
        == "Cluster maintenance"
    )
    assert not kube.configmaps


def test_global_disable_suspends_and_enable_does_not_restart(setup):
    browser, store, _, _ = setup
    first, second = store.create(OWNER).reference, store.create(OTHER).reference
    result = browser.put(
        BASE + "/admin/controls",
        headers=HEADERS,
        json=global_body(browser, sandboxes_disabled=True),
    )
    assert result.status_code == 200 and not result.json()["suspension_failures"]
    for cr in (first, second):
        current = store.admin_get(
            cr["metadata"]["name"], cr["metadata"]["namespace"]
        ).reference
        assert current["spec"]["operatingMode"] == "Suspended"
    assert browser.post(BASE + "/sandboxes", headers=BOB).status_code == 403
    result = browser.put(
        BASE + "/admin/controls",
        headers=HEADERS,
        json=global_body(browser, sandboxes_disabled=False),
    )
    assert result.status_code == 200
    assert (
        store.get(second["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )


def test_user_access_policy_suspends_only_that_owners_sandboxes(setup):
    browser, store, _, _ = setup
    first, second = store.create(OWNER).reference, store.create(OTHER).reference
    result = browser.put(
        BASE + "/admin/controls",
        headers=HEADERS,
        json=global_body(browser, users={OTHER: {"sandboxes_disabled": True}}),
    )
    assert result.status_code == 200
    assert (
        store.get(first["metadata"]["name"], OWNER).reference["spec"]["operatingMode"]
        == "Running"
    )
    assert (
        store.get(second["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )
    personal = browser.get(BASE + "/sandboxes", headers=HEADERS).json()
    assert "users" not in personal and "controls" not in personal


def test_global_notice_persists_is_public_to_signed_in_users_and_can_be_cleared(setup):
    browser, store, kube, settings = setup
    body = global_body(
        browser,
        announcement={
            "title": "Maintenance tonight",
            "body": "Line one\n<script>alert(1)</script>",
        },
    )
    assert (
        browser.put(BASE + "/admin/controls", headers=HEADERS, json=body).status_code
        == 200
    )
    record = browser.get(BASE + "/sandboxes", headers=BOB).json()["announcement"]
    assert record["author"] == OWNER and "<script>" in record["body"]
    restored = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=store.integrations.catalog.namespaces,
        metadata=kube.metadata,
    )
    assert restored.controls.read()[0].announcement.title == record["title"]
    assert (
        browser.put(
            BASE + "/admin/controls",
            headers=HEADERS,
            json=global_body(browser, announcement={"title": "", "body": ""}),
        ).status_code
        == 200
    )
    assert browser.get(BASE + "/sandboxes", headers=BOB).json()["announcement"] is None


@pytest.mark.parametrize("headers", [BOB, {"Origin": SETTINGS.origin}])
def test_controls_require_seeded_admin_and_origin(setup, headers):
    browser, store, _, _ = setup
    cr = store.create(OTHER).reference
    assert browser.put(
        target(cr), headers=headers, json={"resource_version": "2", "disabled": True}
    ).status_code in {401, 403}
    assert browser.put(
        BASE + "/admin/controls",
        headers=headers,
        json={
            "resource_version": "2",
            "creation_disabled": True,
            "sandboxes_disabled": False,
        },
    ).status_code in {401, 403}
    assert (
        browser.put(
            target(cr),
            headers={**HEADERS, "Origin": "https://evil.test"},
            json={"resource_version": "2", "disabled": True},
        ).status_code
        == 403
    )
    assert not sandbox_control(store.get(cr["metadata"]["name"], OTHER)).disabled


def test_stale_versions_and_uid_cannot_overwrite_controls(setup):
    browser, store, _, _ = setup
    cr = store.create(OTHER).reference
    assert (
        browser.put(
            target(cr).replace(cr["metadata"]["uid"], "stale"),
            headers=HEADERS,
            json={"resource_version": "2", "disabled": True},
        ).status_code
        == 409
    )
    assert (
        browser.put(
            target(cr),
            headers=HEADERS,
            json={"resource_version": "stale", "disabled": True},
        ).status_code
        == 409
    )
    body = global_body(browser, creation_disabled=True)
    assert (
        browser.put(BASE + "/admin/controls", headers=HEADERS, json=body).status_code
        == 200
    )
    assert (
        browser.put(
            BASE + "/admin/controls",
            headers=HEADERS,
            json={**body, "creation_disabled": False},
        ).status_code
        == 409
    )
    assert store.controls.read()[0].creation_disabled


def test_policy_reads_fail_closed_and_invalid_messages_rejected(setup):
    browser, store, kube, _ = setup
    cr = store.create(OTHER).reference
    assert (
        browser.put(
            target(cr),
            headers=HEADERS,
            json={"resource_version": "2", "notice": {"title": "only title"}},
        ).status_code
        == 422
    )
    assert (
        browser.put(
            target(cr),
            headers=HEADERS,
            json={"resource_version": "2", "reason": "x" * 501},
        ).status_code
        == 422
    )
    store.metadata.get_controls = Mock(side_effect=StorageError("unavailable"))
    assert browser.post(BASE + "/sandboxes", headers=BOB).status_code == 503
    assert (
        browser.post(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resume", headers=BOB
        ).status_code
        == 503
    )


@pytest.mark.parametrize("failure", ["disabled", "metadata"])
def test_live_user_terminal_is_closed_after_access_check_fails(
    setup, monkeypatch, failure
):
    import portal.app as module

    browser, store, _, _ = setup
    cr = store.create(OTHER).reference

    class Exec:
        opened = True
        text = "shell ready\r\n"

        def is_open(self):
            return self.opened

        def update(self, timeout):
            pass

        def read_all(self):
            result, self.text = self.text, ""
            return result

        def close(self):
            self.opened = False

    connection = Exec()
    monkeypatch.setattr(execution, "stream", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(module, "AUTH_RECHECK_SECONDS", 0.01)
    name = cr["metadata"]["name"]
    with browser.websocket_connect(
        BASE + f"/sandboxes/{name}/terminal", headers=BOB
    ) as ws:
        assert ws.receive_json(mode="binary") == {"type": "ready"}
        assert ws.receive_text() == "shell ready\r\n"
        if failure == "metadata":
            monkeypatch.setattr(
                store.metadata,
                "get_controls",
                Mock(side_effect=StorageError("unavailable")),
            )
        else:
            result = browser.put(
                target(cr),
                headers=HEADERS,
                json={"resource_version": "2", "disabled": True},
            )
            assert result.status_code == 200
        assert ws.receive_json(mode="binary")["code"] == (
            "metadata-unavailable" if failure == "metadata" else "http-403"
        )
    assert not connection.opened


def test_notice_clear_and_forged_authorship_rejection(setup):
    browser, store, _kube, _settings = setup
    cr = store.create(OTHER).reference
    assert (
        browser.put(
            target(cr),
            headers=HEADERS,
            json={
                "resource_version": "2",
                "notice": {"title": "Title", "body": "Body", "author": "attacker"},
            },
        ).status_code
        == 422
    )
    response = browser.put(
        target(cr),
        headers=HEADERS,
        json={"resource_version": "2", "notice": {"title": "Title", "body": "Body"}},
    )
    assert response.status_code == 200
    current = store.get(cr["metadata"]["name"], OTHER).reference
    cleared = browser.put(
        target(current),
        headers=HEADERS,
        json={
            "resource_version": as_sandbox(store, current).resource_version,
            "notice": {"title": "", "body": ""},
        },
    )
    assert (
        cleared.status_code == 200 and cleared.json()["admin_control"]["notice"] is None
    )


def test_disable_between_route_guard_and_resume_is_rechecked(setup, monkeypatch):
    browser, store, _kube, _settings = setup
    cr = store.create(OTHER).reference
    original = store.mode

    def racing_resume(name, owner, mode):
        current = store.get(name, owner).reference
        meta = current["metadata"]
        store.admin_control(
            name,
            meta["namespace"],
            meta["uid"],
            SandboxUpdate(
                resource_version=as_sandbox(store, current).resource_version,
                disabled=True,
            ),
            OWNER,
        ).reference
        return original(name, owner, mode)

    monkeypatch.setattr(store, "mode", racing_resume)
    assert (
        browser.post(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resume", headers=BOB
        ).status_code
        == 403
    )
    assert (
        store.get(cr["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )


def test_admin_can_delete_disabled_sandbox(setup):
    browser, store, _kube, _settings = setup
    cr = store.create(OTHER).reference
    meta = cr["metadata"]
    store.admin_control(
        meta["name"],
        meta["namespace"],
        meta["uid"],
        SandboxUpdate(
            resource_version=as_sandbox(store, cr).resource_version, disabled=True
        ),
        OWNER,
    ).reference
    path = (
        BASE
        + f"/admin/sandboxes/{meta['name']}?namespace={meta['namespace']}&uid={meta['uid']}"
    )
    assert browser.delete(path, headers=HEADERS).status_code == 202


def test_admin_cannot_resume_disabled_sandbox_then_reenables_before_starting(setup):
    browser, store, _kube, _settings = setup
    cr = store.create(OTHER).reference
    assert (
        browser.put(
            target(cr),
            headers=HEADERS,
            json={"resource_version": "2", "disabled": True},
        ).status_code
        == 200
    )
    current = store.get(cr["metadata"]["name"], OTHER).reference
    stopped = browser.put(
        target(current),
        headers=HEADERS,
        json={
            "resource_version": as_sandbox(store, current).resource_version,
            "operating_mode": "Suspended",
        },
    )
    assert stopped.status_code == 200 and stopped.json()["admin_control"]["disabled"]
    current = store.get(cr["metadata"]["name"], OTHER).reference
    assert current["spec"]["operatingMode"] == "Suspended"
    resumed = browser.put(
        target(current),
        headers=HEADERS,
        json={
            "resource_version": as_sandbox(store, current).resource_version,
            "operating_mode": "Running",
        },
    )
    assert resumed.status_code == 409
    assert (
        store.get(cr["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )
    assert (
        browser.post(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resume", headers=BOB
        ).status_code
        == 403
    )
    enabled = browser.put(
        target(current),
        headers=HEADERS,
        json={
            "resource_version": as_sandbox(store, current).resource_version,
            "disabled": False,
        },
    )
    assert enabled.status_code == 200
    assert (
        store.get(cr["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )
    assert (
        browser.post(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resume", headers=BOB
        ).status_code
        == 200
    )
    assert (
        store.get(cr["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Running"
    )


def damage_policy(metadata, failure):
    if failure == "unavailable":
        metadata.get_controls = Mock(side_effect=StorageError("Database unavailable"))
    else:
        with metadata.engine.begin() as connection:
            if failure == "missing":
                connection.execute(controls.delete())
            else:
                connection.execute(controls.update().values(policy={"users": []}))


@pytest.mark.parametrize("failure", ["missing", "malformed", "unavailable"])
def test_required_policy_failure_aborts_startup_without_repair(failure):
    settings = replace(SETTINGS, admin_emails=json.dumps([OWNER]))
    kube = AdminKubernetes()
    damage_policy(kube.metadata, failure)
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    with (
        pytest.raises(RuntimeError, match="controls|metadata|Database"),
        TestClient(create_app(settings, store, Omnigent())),
    ):
        pass
    if failure == "missing":
        with kube.metadata.engine.connect() as connection:
            assert (
                connection.scalar(sa.select(sa.func.count()).select_from(controls)) == 0
            )


def test_deleted_policy_fails_readiness_access_and_saves_but_not_liveness(setup):
    browser, store, _, _ = setup
    body = global_body(browser)
    damage_policy(store.metadata, "missing")
    assert browser.get("/readyz").status_code == 503
    assert browser.get("/healthz").status_code == 200
    assert browser.get(BASE + "/admin/sandboxes", headers=HEADERS).status_code == 503
    assert browser.get(BASE + "/sandboxes", headers=HEADERS).status_code == 503
    assert (
        browser.put(BASE + "/admin/controls", headers=HEADERS, json=body).status_code
        == 503
    )


def test_admin_controls_do_not_read_or_patch_kubernetes_configmaps(setup):
    browser, store, kube, _ = setup
    kube.read_namespaced_config_map = Mock(
        side_effect=AssertionError("No policy ConfigMap")
    )
    kube.patch_namespaced_config_map = Mock(
        side_effect=AssertionError("No policy ConfigMap")
    )
    assert (
        browser.put(
            BASE + "/admin/controls",
            headers=HEADERS,
            json=global_body(browser, creation_disabled=True),
        ).status_code
        == 200
    )
    assert store.controls.read()[0].creation_disabled
    kube.read_namespaced_config_map.assert_not_called()
    kube.patch_namespaced_config_map.assert_not_called()


def test_deleted_policy_fails_closed_without_resuming_suspended_workloads(setup):
    browser, store, kube, settings = setup
    cr = store.create(OTHER).reference
    assert (
        browser.put(
            BASE + "/admin/controls",
            headers=HEADERS,
            json=global_body(browser, sandboxes_disabled=True),
        ).status_code
        == 200
    )
    assert store.get(cr["metadata"]["name"], OTHER).requested_mode == "Suspended"
    damage_policy(store.metadata, "missing")
    restored = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=store.integrations.catalog.namespaces,
        metadata=kube.metadata,
    )
    with pytest.raises(StorageError):
        restored.check_access(as_sandbox(restored, cr))
    assert browser.post(BASE + "/sandboxes", headers=BOB).status_code == 503
    assert browser.get("/readyz").status_code == 503
    assert store.get(cr["metadata"]["name"], OTHER).requested_mode == "Suspended"


def test_reconciler_retries_conflicts_and_repairs_out_of_band_resume(
    setup, monkeypatch
):
    _, store, kube, settings = setup
    cr = store.create(OTHER).reference
    meta = cr["metadata"]
    store.controls.save(
        GlobalUpdate(
            resource_version=store.controls.read()[1],
            creation_disabled=False,
            sandboxes_disabled=True,
        ),
        OWNER,
    )
    patch = kube.patch_namespaced_custom_object
    monkeypatch.setattr(
        kube, "patch_namespaced_custom_object", Mock(side_effect=ApiException(409))
    )
    failures = store.reconcile_controls()
    assert failures == [
        {
            "name": meta["name"],
            "namespace": meta["namespace"],
            "error": "Sandbox suspension needs administrator attention",
        }
    ]
    assert (
        store.get(meta["name"], OTHER).reference["spec"]["operatingMode"] == "Running"
    )
    monkeypatch.setattr(kube, "patch_namespaced_custom_object", patch)
    replica = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=store.integrations.catalog.namespaces,
        metadata=kube.metadata,
    )
    assert replica.reconcile_controls() == []
    assert (
        store.get(meta["name"], OTHER).reference["spec"]["operatingMode"] == "Suspended"
    )
    current = store.get(meta["name"], OTHER).reference
    patch(
        "agents.x-k8s.io",
        "v1beta1",
        meta["namespace"],
        "sandboxes",
        meta["name"],
        {
            "metadata": {"resourceVersion": current["metadata"]["resourceVersion"]},
            "spec": {"operatingMode": "Running"},
        },
    )
    assert store.reconcile_controls() == []
    assert (
        store.get(meta["name"], OTHER).reference["spec"]["operatingMode"] == "Suspended"
    )
    patch_mock = Mock(wraps=patch)
    monkeypatch.setattr(kube, "patch_namespaced_custom_object", patch_mock)
    assert replica.reconcile_controls() == []
    patch_mock.assert_not_called()


def test_global_disable_reports_failures_and_keeps_durable_intent(setup, monkeypatch):
    browser, store, kube, _ = setup
    cr = store.create(OTHER).reference
    patch = kube.patch_namespaced_custom_object
    monkeypatch.setattr(
        kube, "patch_namespaced_custom_object", Mock(side_effect=ApiException(403))
    )
    result = browser.put(
        BASE + "/admin/controls",
        headers=HEADERS,
        json=global_body(browser, sandboxes_disabled=True),
    )
    assert result.status_code == 200 and result.json()["suspension_failures"]
    assert store.controls.read()[0].sandboxes_disabled
    assert (
        browser.post(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resume", headers=BOB
        ).status_code
        == 403
    )
    monkeypatch.setattr(kube, "patch_namespaced_custom_object", patch)
    assert store.reconcile_controls() == []


def test_invalid_target_metadata_does_not_prevent_other_suspensions(setup):
    _, store, kube, _ = setup
    first, second = store.create(OWNER).reference, store.create(OTHER).reference
    meta = first["metadata"]
    kube.items[(meta["namespace"], meta["name"])]["metadata"]["annotations"][
        PREFIX + "admin-control"
    ] = '{"disabled":"invalid"}'
    store.controls.save(
        GlobalUpdate(
            resource_version=store.controls.read()[1],
            creation_disabled=False,
            sandboxes_disabled=True,
        ),
        OWNER,
    )
    failures = store.reconcile_controls()
    assert failures == []
    assert store.get(meta["name"], OWNER).control.disabled is False
    assert (
        store.get(second["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )


def test_global_restriction_cannot_be_bypassed_by_local_reenable_or_admin_resume(setup):
    browser, store, _, _ = setup
    cr = store.create(OTHER).reference
    assert (
        browser.put(
            BASE + "/admin/controls",
            headers=HEADERS,
            json=global_body(browser, users={OTHER: {"sandboxes_disabled": True}}),
        ).status_code
        == 200
    )
    current = store.get(cr["metadata"]["name"], OTHER).reference
    assert (
        browser.put(
            target(current),
            headers=HEADERS,
            json={
                "resource_version": as_sandbox(store, current).resource_version,
                "disabled": False,
                "operating_mode": "Running",
            },
        ).status_code
        == 409
    )
    assert (
        store.get(cr["metadata"]["name"], OTHER).reference["spec"]["operatingMode"]
        == "Suspended"
    )


def test_suspending_does_not_set_disabled_intent(setup):
    browser, store, _, _ = setup
    cr = store.create(OTHER).reference
    result = browser.put(
        target(cr),
        headers=HEADERS,
        json={"resource_version": "2", "operating_mode": "Suspended"},
    )
    assert result.status_code == 200 and not result.json()["admin_control"]["disabled"]
    assert (
        browser.post(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resume", headers=BOB
        ).status_code
        == 200
    )


@pytest.mark.parametrize("annotation", ["profile", "shares"])
def test_invalid_profile_or_sharing_does_not_block_admin_suspension(setup, annotation):
    browser, store, kube, _ = setup
    damaged = store.create(OTHER)
    healthy = store.create(OTHER)
    update = GlobalUpdate(**global_body(browser, sandboxes_disabled=True))
    kube.items[(damaged.scope, damaged.name)]["metadata"]["annotations"][
        PREFIX + annotation
    ] = "{"
    store.controls.save(update, OWNER)
    assert store.reconcile_controls() == []
    for sandbox in (damaged, healthy):
        assert (
            kube.items[(sandbox.scope, sandbox.name)]["spec"]["operatingMode"]
            == "Suspended"
        )
    with pytest.raises(HTTPException) as error:
        store.check_access(store.get(damaged.name, OTHER))
    assert error.value.status_code == 403
