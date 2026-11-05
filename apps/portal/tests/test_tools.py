import json
import subprocess
from unittest.mock import Mock

import pytest
from execution_fakes import target as execution_target
from fastapi.testclient import TestClient
from test_portal import (
    BASE,
    HEADERS,
    OTHER,
    OWNER,
    PROFILE_FIXTURES,
    SETTINGS,
    Kubernetes,
    Omnigent,
)

from portal.app import create_app
from portal.namespaces import UserNamespaces
from portal.profiles import Helper
from portal.sandboxes import Store
from portal.tools import (
    MAX_OUTPUT,
    ToolStatus,
    probe_command,
    probe_helper,
    probe_state,
)

HELPERS = [Helper.model_validate(h) for h in PROFILE_FIXTURES[0]["helpers"]]


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


def test_probe_returns_only_states(tmp_path):
    codex = tmp_path / "codex"
    codex.write_text('#!/bin/sh\nprintf "Logged in using ChatGPT\\n"\n')
    codex.chmod(0o700)
    claude = tmp_path / "claude"
    claude.write_text(
        '#!/bin/sh\nprintf \'{"loggedIn":true,"email":"private@example.com","token":"secret"}\\n\'\n'
    )
    claude.chmod(0o700)
    caipe = tmp_path / "caipe"
    caipe.write_text(
        '#!/bin/sh\nprintf \'{"authenticated":true,"identity":"private@example.com"}\\n\'\n'
    )
    caipe.chmod(0o700)

    def states():
        result = {}
        for helper in HELPERS:
            response = subprocess.run(
                probe_command(helper.status),
                env={"PATH": str(tmp_path)},
                capture_output=True,
                text=True,
                check=False,
            )
            result[helper.id] = probe_state(
                helper.status, response.stdout, response.stderr, response.returncode
            )
        return result

    assert states() == {
        "codex-login": "signed-in",
        "claude-login": "signed-in",
        "caipe-login": "signed-in",
    }
    assert "private" not in json.dumps(states()) and "secret" not in json.dumps(
        states()
    )
    codex.write_text('#!/bin/sh\nprintf "Not logged in\\n"; exit 1\n')
    claude.unlink()
    caipe.write_text("#!/bin/sh\nprintf '{\"authenticated\":false}\\n'\n")
    assert states() == {
        "codex-login": "sign-in",
        "claude-login": "unavailable",
        "caipe-login": "sign-in",
    }


def connection(stdout="", stderr="", returncode=0):
    conn = Mock()
    conn.is_open.side_effect = [True, False]
    conn.read_stdout.return_value = stdout
    conn.read_stderr.return_value = stderr
    conn.returncode = returncode
    return conn


def test_status_cache_is_bound_to_provider_incarnation_and_closes_exec(monkeypatch):

    connections = []

    def execute(command, **kwargs):
        assert command[:2] == ["/bin/sh", "-c"]
        assert "python3" not in command
        assert kwargs["stdin"] is False and kwargs["tty"] is False
        stdout = {
            "codex": "Logged in using ChatGPT",
            "claude": '{"loggedIn":true,"token":"secret-in-unexpected-field"}',
            "caipe": "malformed JSON",
        }[command[4]]
        conn = connection(stdout)
        connections.append(conn)
        return conn

    stream = Mock(side_effect=execute)
    pod = execution_target(stream)
    probe = ToolStatus()
    expected = {
        "codex-login": "signed-in",
        "claude-login": "signed-in",
        "caipe-login": "unknown",
    }
    assert probe.status(pod, helpers=HELPERS) == expected
    assert probe.status(pod, helpers=HELPERS) == expected
    assert stream.call_count == 3
    for conn in connections:
        conn.close.assert_called_once()
    pod = execution_target(stream, incarnation="replacement-session")
    assert probe.status(pod, helpers=HELPERS) == expected
    assert stream.call_count == 6


def test_tools_endpoint_checks_owner_before_probe(setup):
    browser, store, _, _ = setup
    cr = store.create(OWNER).reference
    probe = browser.app.state.tools.status = Mock(
        return_value={
            "codex-login": "signed-in",
            "claude-login": "sign-in",
            "caipe-login": "unavailable",
        }
    )
    path = BASE + f"/sandboxes/{cr['metadata']['name']}/tools"
    response = browser.get(path, headers=HEADERS)
    assert response.json() == {
        "tools": {
            "codex-login": "signed-in",
            "claude-login": "sign-in",
            "caipe-login": "unavailable",
        }
    }
    assert response.headers["cache-control"] == "no-store"
    probe.reset_mock()
    assert browser.get(path, headers={"Cookie": "session=bob"}).status_code == 404
    probe.assert_not_called()


def test_fresh_probe_bypasses_the_signed_out_cache(monkeypatch):

    stream = Mock(
        side_effect=[
            connection("Not logged in", returncode=1),
            connection("Logged in using ChatGPT"),
        ]
    )
    pod = execution_target(stream)
    probe = ToolStatus()
    helpers = [HELPERS[0]]
    assert probe.status(pod, helpers=helpers)["codex-login"] == "sign-in"
    assert probe.status(pod, helpers=helpers)["codex-login"] == "sign-in"
    assert probe.status(pod, fresh=True, helpers=helpers)["codex-login"] == "signed-in"
    assert stream.call_count == 2


def test_probe_deadline_closes_exec_and_returns_unknown(monkeypatch):
    import portal.tools as module

    conn = Mock()
    conn.is_open.return_value = True
    stream = Mock(return_value=conn)
    monkeypatch.setattr(module.time, "monotonic", Mock(side_effect=[0, 9]))
    pod = execution_target(stream)
    assert probe_helper(pod, HELPERS[0]) == ("codex-login", "unknown")
    conn.update.assert_not_called()
    conn.close.assert_called_once()


@pytest.mark.parametrize("channel", ["stdout", "stderr"])
def test_probe_output_is_bounded_and_never_exposed(monkeypatch, channel):

    conn = connection(**{channel: "x" * (MAX_OUTPUT + 1)})
    stream = Mock(return_value=conn)
    pod = execution_target(stream)
    assert probe_helper(pod, HELPERS[0]) == ("codex-login", "unknown")
    conn.close.assert_called_once()


@pytest.mark.parametrize("error", [TimeoutError(), ValueError(), KeyError("status")])
def test_probe_transport_errors_fail_closed(monkeypatch, error):

    stream = Mock(side_effect=error)
    pod = execution_target(stream)
    assert probe_helper(pod, HELPERS[0]) == ("codex-login", "unknown")


def test_probe_output_limit_counts_utf8_bytes(monkeypatch):

    conn = connection("é" * (MAX_OUTPUT // 2 + 1))
    stream = Mock(return_value=conn)
    pod = execution_target(stream)
    assert probe_helper(pod, HELPERS[0]) == ("codex-login", "unknown")
    conn.close.assert_called_once()


def test_helpers_without_status_never_open_exec(monkeypatch):

    execute = Mock()
    stream = execute
    pod = execution_target(stream)
    helper = Helper(id="workspace", title="Workspace", script="pwd")
    assert ToolStatus().status(pod, helpers=[helper]) == {"workspace": "unknown"}
    execute.assert_not_called()


def test_status_cache_is_bound_to_probe_definition(monkeypatch):

    execute = Mock(side_effect=[connection(returncode=0), connection(returncode=4)])
    stream = execute
    pod = execution_target(stream)
    first = Helper(
        id="custom", title="Custom", script="login", status={"command": ["first"]}
    )
    second = first.model_copy(
        update={
            "status": first.status.model_copy(
                update={
                    "command": ["second"],
                    "signed_out_exit_codes": [4],
                }
            )
        }
    )
    probe = ToolStatus()
    assert probe.status(pod, helpers=[first]) == {"custom": "signed-in"}
    assert probe.status(pod, helpers=[second]) == {"custom": "sign-in"}
    assert execute.call_count == 2


def test_fresh_endpoint_still_checks_shell_access(setup):
    browser, store, _, _ = setup
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    probe = browser.app.state.tools.status = Mock(
        return_value={"codex-login": "signed-in"}
    )
    response = browser.get(
        BASE + f"/sandboxes/{name}/tools?fresh=true", headers=HEADERS
    )
    assert response.status_code == 200
    assert probe.call_args.kwargs["fresh"] is True
    assert {h.id for h in probe.call_args.kwargs["helpers"]} == {
        "codex-login",
        "claude-login",
        "caipe-login",
    }
    probe.reset_mock()
    store.sharing(name, OWNER, {OTHER: "view"}).reference
    assert (
        browser.get(
            BASE + f"/sandboxes/{name}/tools?fresh=true&owner={OWNER}",
            headers={"Cookie": "session=bob"},
        ).status_code
        == 404
    )
    probe.assert_not_called()


@pytest.mark.parametrize("grant,status", [("view", 404), ("shell", 200)])
def test_shared_tool_status_requires_shell_permission(setup, grant, status):
    browser, store, _, _ = setup
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    store.sharing(name, OWNER, {OTHER: grant}).reference
    probe = browser.app.state.tools.status = Mock(
        return_value={
            "codex-login": "signed-in",
            "claude-login": "sign-in",
            "caipe-login": "unavailable",
        }
    )
    assert (
        browser.get(
            BASE + f"/sandboxes/{name}/tools",
            params={"owner": OWNER},
            headers={"Cookie": "session=bob"},
        ).status_code
        == status
    )
    assert probe.call_count == (1 if status == 200 else 0)
