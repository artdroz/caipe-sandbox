import json
from unittest.mock import Mock

import pytest
from execution_fakes import target as execution_target
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, OTHER, OWNER, SETTINGS, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.workspace import Workspace


@pytest.fixture
def setup():
    store, kube = store_for()
    cr = store.create(OWNER).reference
    workspace = Mock()
    workspace.run.return_value = {
        "protocol_version": 1,
        "files": {"startup": [], "service": []},
        "services": [],
        "startup": [],
        "service_errors": [],
    }
    with TestClient(create_app(SETTINGS, store, Omnigent(), workspace)) as browser:
        yield browser, store, kube, cr, workspace


def target(cr):
    return (
        BASE
        + f"/sandboxes/{cr['metadata']['name']}/workspace?uid={cr['metadata']['uid']}"
    )


def test_workspace_requires_login_origin_uid_and_running_sandbox(setup):
    browser, store, kube, cr, workspace = setup
    path = target(cr)
    assert browser.get(path).status_code == 401
    assert browser.get(path, headers=HEADERS).status_code == 200
    assert (
        browser.post(
            path, headers={"Cookie": "session=alice"}, json={"action": "apply"}
        ).status_code
        == 403
    )
    assert (
        browser.get(
            path.replace(cr["metadata"]["uid"], "wrong"), headers=HEADERS
        ).status_code
        == 409
    )
    store.mode(cr["metadata"]["name"], OWNER, "Suspended").reference
    assert browser.get(path, headers=HEADERS).status_code == 409
    assert workspace.run.call_count == 1


def test_workspace_requires_shell_permission_and_rechecks_revocation(setup):
    browser, store, _, cr, workspace = setup
    name = cr["metadata"]["name"]
    path = target(cr) + "&owner=" + OWNER
    headers = {"Cookie": "session=bob", "Origin": SETTINGS.origin}
    store.sharing(name, OWNER, {OTHER: "view"}).reference
    assert browser.get(path, headers=headers).status_code == 404
    store.sharing(name, OWNER, {OTHER: "shell"}).reference
    assert (
        browser.post(
            path,
            headers=headers,
            json={
                "action": "save",
                "kind": "startup",
                "name": "10-setup.sh",
                "content": "echo ok",
            },
        ).status_code
        == 200
    )
    store.sharing(name, OWNER, {}).reference
    assert browser.get(path, headers=headers).status_code == 404
    assert workspace.run.call_count == 1


def test_disabled_sandbox_and_invalid_requests_never_execute(setup):
    browser, store, _, cr, workspace = setup
    path = target(cr)
    for body in (
        {"action": "exec", "command": "whoami"},
        {"action": "save", "name": "../tokens.sh"},
        {
            "action": "save",
            "kind": "startup",
            "name": "large.sh",
            "content": "x" * 65537,
        },
    ):
        assert browser.post(path, headers=HEADERS, json=body).status_code == 422
    from portal.controls import GlobalUpdate

    store.controls.save(
        GlobalUpdate(
            resource_version="1", creation_disabled=False, sandboxes_disabled=True
        ),
        OWNER,
    )
    assert browser.get(path, headers=HEADERS).status_code == 403
    workspace.run.assert_not_called()


class Connection:
    returncode = 0

    def __init__(self, response):
        self.response = response
        self.open = True
        self.closed = False

    def write_stdin(self, value):
        self.input = value

    def is_open(self):
        return self.open

    def update(self, **kwargs):
        self.open = False

    def read_stdout(self, **kwargs):
        return self.response

    def read_stderr(self, **kwargs):
        return "private transport details"

    def close(self):
        self.closed = True


def test_workspace_transport_uses_fixed_command_json_stdin_and_closes(monkeypatch):
    conn = Connection('{"saved":true}')
    stream = Mock(return_value=conn)
    body = {
        "action": "save",
        "kind": "startup",
        "name": "example.sh",
        "content": "echo '$(touch injected)'\n",
    }
    pod = execution_target(stream)
    assert Workspace().run(pod, body) == {"saved": True}
    assert stream.call_args.args[0] == ["/usr/local/bin/sandbox-control"]
    assert json.loads(conn.input) == body
    assert conn.closed


@pytest.mark.parametrize(
    "response,returncode,status",
    [
        ("not json", 0, 503),
        ("{}", 127, 501),
        ('{"error":"File changed","code":409}', 0, 409),
        ("x" * 262145, 0, 502),
    ],
)
def test_workspace_transport_errors_are_bounded_and_hide_stderr(
    monkeypatch, response, returncode, status
):
    conn = Connection(response)
    conn.returncode = returncode
    stream = Mock(return_value=conn)
    pod = execution_target(stream)
    with pytest.raises(HTTPException) as caught:
        Workspace().run(pod, {"action": "inspect"})
    assert caught.value.status_code == status
    assert "private transport details" not in caught.value.detail
    assert conn.closed


def test_mock_service_review_ignores_comments_and_never_starts_real_processes():
    from preview_workspace import PreviewWorkspace

    workspace = PreviewWorkspace()
    connector = Mock()
    execution = execution_target(connector)
    body = {"kind": "service", "name": "omnigent.conf"}
    workspace.run(execution, {"action": "inspect"})
    current = workspace.run(execution, {**body, "action": "read"})
    saved = workspace.run(
        execution,
        {
            **body,
            "action": "save",
            "content": current["content"] + "\n# comment\n",
            "revision": current["revision"],
        },
    )
    assert workspace.run(execution, {"action": "preview"})["operations"] == []
    workspace.run(
        execution,
        {
            **body,
            "action": "save",
            "content": current["content"].replace("command=", "command=env TEST=1 "),
            "revision": saved["revision"],
        },
    )
    assert (
        workspace.run(execution, {"action": "preview"})["operations"][0]["action"]
        == "restart"
    )
    connector.assert_not_called()
