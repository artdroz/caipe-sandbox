import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_portal import BASE, HEADERS, OTHER, OWNER, SETTINGS, Kubernetes, Omnigent

from portal.app import create_app
from portal.integrations.agent_sandbox import execution
from portal.integrations.agent_sandbox.inventory import PREFIX
from portal.namespaces import UserNamespaces
from portal.sandboxes import Store


@pytest.fixture
def setup():
    kube, upstream = Kubernetes(), Omnigent()
    store = Store(
        SETTINGS,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(SETTINGS, kube, kube, kube),
        metadata=kube.metadata,
    )
    with TestClient(create_app(SETTINGS, store, upstream)) as browser:
        yield browser, store, kube, upstream


BOB = {"Origin": SETTINGS.origin, "Cookie": "session=bob"}


def test_namespace_grants_live_in_database_and_cover_all_sibling_sandboxes(setup):
    browser, store, kube, _ = setup
    first, second = store.create(OWNER).reference, store.create(OWNER).reference
    name = first["metadata"]["name"]
    path = BASE + f"/sandboxes/{name}/sharing"
    result = browser.put(
        path, headers=HEADERS, json={"members": {OTHER.upper(): "shell"}}
    )
    assert result.status_code == 200 and result.json()["members"] == {OTHER: "shell"}
    cr = kube.items[(first["metadata"]["namespace"], name)]
    assert store.get(name, OWNER).record.grants == {OTHER: "shell"}
    assert PREFIX + "shares" not in cr["metadata"]["annotations"]
    response = browser.get(BASE + "/sandboxes", params={"owner": OWNER}, headers=BOB)
    assert response.status_code == 200
    rows = response.json()["sandboxes"]
    assert {r["id"] for r in rows} == {name, second["metadata"]["name"]}
    assert all(r["can_shell"] and not r["can_manage"] for r in rows)
    assert rows[0]["can_shell"] and not rows[0]["can_manage"]
    assert rows[0]["owner"] == OWNER and rows[0]["sharing"] == {}
    assert (
        store.shared_get(name, OTHER, OWNER, shell=True).reference["metadata"]["uid"]
        == cr["metadata"]["uid"]
    )
    assert second["metadata"]["name"] != name
    future = store.create(OWNER)
    assert store.shared_get(future.name, OTHER, OWNER, shell=True).uid == future.uid
    assert browser.get(BASE + "/sandboxes", headers=BOB).json()["sandboxes"] == []


@pytest.mark.parametrize(
    "members",
    [{OWNER: "shell"}, {"not-an-email": "view"}, {OTHER: "admin"}, {OTHER: "delete"}],
)
def test_invalid_share_grants_rejected(setup, members):
    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    assert (
        browser.put(
            BASE + f"/sandboxes/{name}/sharing",
            headers=HEADERS,
            json={"members": members},
        ).status_code
        == 422
    )


def test_shared_user_cannot_manage_lifecycle_credentials_or_sharing(setup):
    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    store.sharing(name, OWNER, {OTHER: "shell"}).reference
    suffix = "?owner=" + OWNER
    for action in ("suspend", "resume"):
        assert (
            browser.post(
                BASE + f"/sandboxes/{name}/{action}" + suffix, headers=BOB
            ).status_code
            == 404
        )
    assert (
        browser.delete(BASE + f"/sandboxes/{name}" + suffix, headers=BOB).status_code
        == 404
    )
    assert (
        browser.put(
            BASE + f"/sandboxes/{name}/sharing" + suffix,
            headers=BOB,
            json={"members": {}},
        ).status_code
        == 404
    )


def test_view_only_and_revoked_grant_cannot_open_terminal(setup):
    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    store.sharing(name, OWNER, {OTHER: "view"}).reference
    response = browser.get(BASE + "/sandboxes", params={"owner": OWNER}, headers=BOB)
    assert not response.json()["sandboxes"][0]["can_shell"]
    with pytest.raises(WebSocketDisconnect):
        with browser.websocket_connect(
            BASE + f"/sandboxes/{name}/terminal?owner={OWNER}", headers=BOB
        ) as ws:
            assert ws.receive_json(mode="binary")["code"] == "http-404"
            ws.receive_text()
    store.sharing(name, OWNER, {}).reference
    assert (
        browser.get(BASE + "/sandboxes", params={"owner": OWNER}, headers=BOB).json()[
            "sandboxes"
        ]
        == []
    )
    with pytest.raises(HTTPException):
        store.shared_get(name, OTHER, OWNER).reference


def test_native_owner_annotation_cannot_change_database_ownership_or_grants(setup):
    _, store, kube, _ = setup
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    store.sharing(name, OWNER, {OTHER: "shell"}).reference
    kube.items[(cr["metadata"]["namespace"], name)]["metadata"]["annotations"][
        PREFIX + "owner"
    ] = OTHER
    assert store.shared_get(name, OTHER, OWNER).owner == OWNER
    with pytest.raises(HTTPException):
        store.get(name, OTHER)


@pytest.mark.parametrize(
    "content", ["invalid-json", '["bob@example.com"]', '{"bob@example.com":"admin"}']
)
def test_malformed_native_annotations_cannot_grant_or_revoke_access(setup, content):
    _, store, kube, _ = setup
    sandbox = store.create(OWNER)
    kube.items[(sandbox.scope, sandbox.name)]["metadata"]["annotations"][
        PREFIX + "shares"
    ] = content
    assert store.get(sandbox.name, OWNER).grants == {}
    with pytest.raises(HTTPException):
        store.shared_get(sandbox.name, OTHER, OWNER)
    store.sharing(sandbox.name, OWNER, {OTHER: "view"})
    assert store.shared_get(sandbox.name, OTHER, OWNER).grants == {OTHER: "view"}


def test_revoking_shell_share_closes_an_existing_terminal(setup, monkeypatch):
    import portal.app as module

    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    store.sharing(name, OWNER, {OTHER: "shell"}).reference
    closed = threading.Event()

    class Exec:
        opened = True
        prompt = "$ "

        def is_open(self):
            return self.opened

        def update(self, timeout):
            pass

        def read_all(self):
            value, self.prompt = self.prompt, ""
            return value

        def read_channel(self, channel):
            return ""

        def close(self):
            self.opened = False
            closed.set()

    terminal = Exec()
    monkeypatch.setattr(execution, "stream", lambda *args, **kwargs: terminal)
    monkeypatch.setattr(module, "AUTH_RECHECK_SECONDS", 0.01)
    with browser.websocket_connect(
        BASE + f"/sandboxes/{name}/terminal?owner={OWNER}", headers=BOB
    ) as ws:
        assert ws.receive_json(mode="binary") == {"type": "ready"}
        assert ws.receive_text() == "$ "
        store.sharing(name, OWNER, {}).reference
        assert closed.wait(2)
        assert ws.receive_json(mode="binary")["code"] == "http-404"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_separate_namespace_sharing_never_covers_another_namespace(setup):
    from dataclasses import replace

    from test_profiles import store_for

    _, _, kube, _ = setup
    settings = replace(SETTINGS, namespace='{"strategy":"perSandbox"}')
    store, _ = store_for(settings, kube)
    first, second = store.create(OWNER), store.create(OWNER)
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    assert first.scope != second.scope
    assert {s.name for s in store.shared_list(OTHER, OWNER)} == {first.name}
    with pytest.raises(HTTPException):
        store.shared_get(second.name, OTHER, OWNER, shell=True)


def test_stale_namespace_sharing_cannot_overwrite_a_save_from_a_sibling(setup):
    browser, store, _, _ = setup
    first, second = store.create(OWNER), store.create(OWNER)
    store.sharing(first.name, OWNER, {OTHER: "view"})
    response = browser.put(
        BASE + f"/sandboxes/{second.name}/sharing",
        headers=HEADERS,
        json={"members": {OTHER: "shell"}, "revision": second.record.revision},
    )
    assert response.status_code == 409
    assert (
        store.get(first.name, OWNER).grants
        == store.get(second.name, OWNER).grants
        == {OTHER: "view"}
    )
