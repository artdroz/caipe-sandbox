import asyncio
import threading
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from kubernetes.client import ApiException
from test_portal import BASE, HEADERS, OWNER, SETTINGS, Kubernetes, Omnigent

from portal.app import create_app
from portal.integrations.agent_sandbox import execution
from portal.namespaces import UserNamespaces
from portal.sandboxes import Store
from portal.terminal import TerminalIO, attach_exec


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


@pytest.mark.parametrize("private_pool", [False, True])
def test_late_exec_is_closed_after_timeout(private_pool):
    release, started = threading.Event(), threading.Event()
    connection = Mock()

    def factory():
        started.set()
        release.wait(2)
        return connection

    async def run():
        io = TerminalIO(1) if private_pool else None
        try:
            with pytest.raises(TimeoutError):
                await attach_exec(
                    factory, 0.02, run=io.run if io else asyncio.to_thread
                )
            assert started.is_set()
            release.set()
            for _ in range(50):
                if connection.close.called:
                    break
                await asyncio.sleep(0.01)
            connection.close.assert_called_once()
        finally:
            release.set()
            if io:
                io.close()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["authorization", "exec"])
def test_terminal_reports_server_timeout_with_log_id(setup, monkeypatch, caplog, stage):
    import portal.app as module

    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]

    if stage == "authorization":

        async def stalled(*args, **kwargs):
            await asyncio.sleep(1)

        monkeypatch.setattr(browser.app.state.auth, "principal", stalled)
        monkeypatch.setattr(module, "TERMINAL_CONNECT_SECONDS", 0.01)
    else:

        async def timeout(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr(module, "attach_exec", timeout)

    with browser.websocket_connect(
        BASE + f"/sandboxes/{name}/terminal", headers=HEADERS
    ) as ws:
        error = ws.receive_json(mode="binary")
        assert error["type"] == "error" and error["code"] == "server-timeout"
        assert error["stage"] == stage
        assert error["request_id"] in caplog.text
        assert "timed out" in error["message"]


def test_terminal_sanitizes_exec_api_error(setup, monkeypatch):
    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    monkeypatch.setattr(
        execution,
        "stream",
        Mock(side_effect=ApiException(status=403, reason="private-token")),
    )
    with browser.websocket_connect(
        BASE + f"/sandboxes/{name}/terminal", headers=HEADERS
    ) as ws:
        error = ws.receive_json(mode="binary")
        assert error["code"] == "http-503" and error["stage"] == "exec"
        assert "unavailable" in error["message"] and "private-token" not in str(error)


def test_two_terminals_for_one_sandbox_have_independent_exec_connections(
    setup, monkeypatch
):
    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    first_closed, second_closed = threading.Event(), threading.Event()
    first_input, second_input = threading.Event(), threading.Event()

    def connection(closed, received):
        conn = Mock()
        conn.is_open.side_effect = lambda: not closed.is_set()
        conn.update.side_effect = lambda **kwargs: closed.wait(0.01)
        conn.read_all.return_value = ""
        conn.read_channel.return_value = ""
        conn.write_stdin.side_effect = lambda data: received.set()
        conn.close.side_effect = closed.set
        return conn

    first, second = (
        connection(first_closed, first_input),
        connection(second_closed, second_input),
    )
    monkeypatch.setattr(execution, "stream", Mock(side_effect=[first, second]))
    path = BASE + f"/sandboxes/{name}/terminal"
    with browser.websocket_connect(path, headers=HEADERS) as ws1:
        assert ws1.receive_json(mode="binary") == {"type": "ready"}
        with browser.websocket_connect(path, headers=HEADERS) as ws2:
            assert ws2.receive_json(mode="binary") == {"type": "ready"}
            ws1.send_json({"type": "input", "data": "echo first\n"})
            ws2.send_json({"type": "input", "data": "echo second\n"})
            assert first_input.wait(2) and second_input.wait(2)
            first.write_stdin.assert_called_once_with("echo first\n")
            second.write_stdin.assert_called_once_with("echo second\n")
        assert second_closed.wait(2)
        assert not first_closed.is_set()
        first_input.clear()
        ws1.send_json({"type": "input", "data": "still connected\n"})
        assert first_input.wait(2)
        first.write_stdin.assert_called_with("still connected\n")
    assert first_closed.wait(2)
