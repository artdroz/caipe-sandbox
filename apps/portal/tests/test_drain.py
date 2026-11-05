"""Shutdown rejects new work while existing authorized shells finish their window."""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import websocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_portal import BASE, HEADERS, OWNER, SETTINGS, Kubernetes, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.drain import Drain
from portal.integrations.agent_sandbox import execution


class Stream:
    returncode = None

    def __init__(self, audit=None):
        self.closed = threading.Event()
        self.received = threading.Event()
        self.audit = audit

    def is_open(self):
        return not self.closed.is_set()

    def update(self, timeout):
        self.closed.wait(timeout)

    def read_all(self):
        return ""

    def write_stdin(self, data):
        self.received.set()
        if self.audit:
            with self.audit.open("a") as output:
                output.write("input\n")

    def close(self):
        self.closed.set()
        if self.audit:
            with self.audit.open("a") as output:
                output.write("close\n")


@pytest.fixture
def portal(tmp_path):
    settings = replace(SETTINGS, drain_file=str(tmp_path / "drain"))
    store, kube = store_for(settings)
    sandbox = store.create(OWNER)
    app = create_app(settings, store, Omnigent())
    with TestClient(app) as browser:
        yield browser, store, kube, sandbox


@pytest.mark.parametrize("helper", [None, "claude-login"])
def test_draining_rejects_new_work_but_preserves_authorized_active_shell(
    portal, monkeypatch, helper
):
    browser, store, kube, sandbox = portal
    conn = Stream()
    native = store.integrations.items["agentSandbox"]
    monkeypatch.setattr(execution, "stream", Mock(return_value=conn))
    monkeypatch.setattr(native, "delete", Mock())
    monkeypatch.setattr(native, "mode", Mock())
    path = BASE + f"/sandboxes/{sandbox.name}/terminal"
    if helper:
        path += "?helper=" + helper
    with browser.websocket_connect(path, headers=HEADERS) as ws:
        assert ws.receive_json(mode="binary") == {"type": "ready"}
        browser.app.state.drain.begin(1)
        notice = ws.receive_json(mode="binary")
        assert notice["type"] == "draining" and 0 <= notice["seconds_remaining"] <= 1
        assert browser.get("/readyz").status_code == 503
        assert browser.get("/healthz").status_code == 200
        assert browser.get(BASE + "/sandboxes", headers=HEADERS).status_code == 200
        response = browser.post(BASE + "/sandboxes", headers=HEADERS)
        assert response.status_code == 503 and response.headers["retry-after"] == "2"
        assert (
            browser.get(
                BASE + f"/sandboxes/{sandbox.name}/tools", headers=HEADERS
            ).status_code
            == 503
        )
        assert (
            browser.get(
                BASE + f"/sandboxes/{sandbox.name}/workspace?uid={sandbox.uid}",
                headers=HEADERS,
            ).status_code
            == 503
        )
        with browser.websocket_connect(path, headers=HEADERS) as rejected:
            assert rejected.receive_json(mode="binary")["type"] == "draining"
            with pytest.raises(WebSocketDisconnect) as closed:
                rejected.receive_json(mode="binary")
            assert closed.value.code == 1012
        execution.stream.assert_called_once()
        ws.send_json({"type": "input", "data": "echo still connected\n"})
        assert conn.received.wait(1)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json(mode="binary")
        assert closed.value.code == 1012
    assert conn.closed.wait(1)
    native.delete.assert_not_called()
    native.mode.assert_not_called()
    assert store.get(sandbox.name, OWNER).uid == sandbox.uid
    assert (
        len(kube.items) == 1
        and store.metadata.get_sandbox(sandbox.record.id).operation is None
    )


def test_attaching_connection_is_cancelled_and_late_native_exec_is_closed(
    portal, monkeypatch
):
    browser, _, _, sandbox = portal
    entered, release = threading.Event(), threading.Event()
    conn = Stream()

    def attach(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return conn

    monkeypatch.setattr(execution, "stream", attach)
    with browser.websocket_connect(
        BASE + f"/sandboxes/{sandbox.name}/terminal", headers=HEADERS
    ) as ws:
        assert entered.wait(3)
        browser.app.state.drain.begin(3)
        try:
            assert ws.receive_json(mode="binary")["type"] == "draining"
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json(mode="binary")
            assert closed.value.code == 1012
        finally:
            release.set()
        assert conn.closed.wait(3)


def test_authorization_is_rechecked_during_drain(portal, monkeypatch):
    import portal.app as module

    browser, store, _, sandbox = portal
    monkeypatch.setattr(module, "AUTH_RECHECK_SECONDS", 0.02)
    conn = Stream()
    monkeypatch.setattr(execution, "stream", Mock(return_value=conn))
    with browser.websocket_connect(
        BASE + f"/sandboxes/{sandbox.name}/terminal", headers=HEADERS
    ) as ws:
        assert ws.receive_json(mode="binary")["type"] == "ready"
        browser.app.state.drain.begin(3)
        assert ws.receive_json(mode="binary")["type"] == "draining"
        store.metadata.save_controls({"sandboxes_disabled": True}, expected_revision=1)
        error = ws.receive_json(mode="binary")
        assert error["code"] == "http-403"
    assert conn.closed.wait(1)


def test_helper_can_finish_during_drain_without_being_reported_as_interrupted(
    portal, monkeypatch
):
    browser, _, _, sandbox = portal
    conn = Stream()
    monkeypatch.setattr(execution, "stream", Mock(return_value=conn))
    with browser.websocket_connect(
        BASE + f"/sandboxes/{sandbox.name}/terminal?helper=claude-login",
        headers=HEADERS,
    ) as ws:
        assert ws.receive_json(mode="binary")["type"] == "ready"
        browser.app.state.drain.begin(3)
        assert ws.receive_json(mode="binary")["type"] == "draining"
        conn.returncode = 0
        conn.closed.set()
        assert ws.receive_json(mode="binary") == {"type": "complete", "exit_code": 0}


def test_signal_is_idempotent_and_malformed_deadlines_fail_closed(tmp_path):
    drain = Drain(tmp_path / "drain")
    assert drain.remaining() is None
    drain.begin(3)
    deadline = drain.path.read_text()
    drain.begin(60)
    assert drain.path.read_text() == deadline
    for broken in ["", "nan", "inf", "not-a-deadline"]:
        drain.path.write_text(broken)
        assert drain.remaining() == 0
    drain.reset()
    assert drain.remaining() is None


def test_portal_logs_the_configured_drain_window_once_even_without_terminals(
    portal, caplog
):
    browser, _, _, _ = portal
    caplog.set_level("INFO", logger="uvicorn.error")
    browser.app.state.drain.begin(180)
    deadline = time.monotonic() + 2
    message = "Waiting 3 minutes for user terminal sessions to drain"
    while message not in caplog.text and time.monotonic() < deadline:
        time.sleep(0.02)
    assert caplog.text.count(message) == 1
    for _ in range(3):
        assert browser.get("/readyz").status_code == 503
    assert caplog.text.count(message) == 1


def test_admitted_management_operation_can_finish_while_new_mutations_are_rejected(
    portal, monkeypatch
):
    browser, store, _, sandbox = portal
    entered, release = threading.Event(), threading.Event()
    backend = store.integrations.items["agentSandbox"]
    original = backend.mode

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(backend, "mode", blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        operation = pool.submit(
            browser.post, BASE + f"/sandboxes/{sandbox.name}/suspend", headers=HEADERS
        )
        assert entered.wait(3)
        browser.app.state.drain.begin(1)
        try:
            assert (
                browser.post(
                    BASE + f"/sandboxes/{sandbox.name}/resume", headers=HEADERS
                ).status_code
                == 503
            )
        finally:
            release.set()
        assert operation.result(timeout=5).status_code == 200
    saved = store.metadata.get_sandbox(sandbox.record.id)
    assert saved.operation is None and saved.requested_mode == "suspended"
    assert saved.binding == sandbox.record.binding


def server_app():
    """Real Uvicorn process with an inert provider; no cluster or native commands."""
    settings = replace(
        SETTINGS,
        drain_file=os.environ["PORTAL_DRAIN_FILE"],
        drain_seconds=int(os.environ["PORTAL_DRAIN_SECONDS"]),
    )
    store, _ = store_for(settings, Kubernetes())
    store.create(OWNER)
    audit = Path(os.environ["PORTAL_DRAIN_TEST_AUDIT"])
    execution.stream = lambda *args, **kwargs: Stream(audit)
    return create_app(settings, store, Omnigent())


def test_real_prestop_process_and_sigterm_close_without_restarting_micro_vm(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = {
        **os.environ,
        "WEB_CONCURRENCY": "1",
        "PYTHONPATH": os.pathsep.join(sys.path),
        "PORTAL_DRAIN_FILE": str(tmp_path / "drain"),
        "PORTAL_DRAIN_TEST_AUDIT": str(tmp_path / "exec-audit"),
        "PORTAL_DRAIN_PROPAGATION_SECONDS": "0",
        "PORTAL_DRAIN_SECONDS": "3",
    }
    with (tmp_path / "server.log").open("w+") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "test_drain:server_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--timeout-graceful-shutdown",
                "2",
            ],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        hook = None
        ws = None
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", headers=HEADERS, timeout=1
            ) as http:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        if http.get("/readyz").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        log.seek(0)
                        pytest.fail("Test portal failed to start: " + log.read())
                    time.sleep(0.05)
                original = http.get(BASE + "/sandboxes").json()["sandboxes"][0]
                ws = websocket.create_connection(
                    f"ws://127.0.0.1:{port}{BASE}/sandboxes/{original['id']}/terminal",
                    origin=SETTINGS.origin,
                    cookie="session=alice",
                    timeout=5,
                )
                assert json.loads(ws.recv())["type"] == "ready"
                hook = subprocess.Popen(
                    [sys.executable, "-m", "portal.drain"],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                assert json.loads(ws.recv())["type"] == "draining"
                assert (
                    http.get("/readyz").status_code == 503
                    and http.get("/healthz").status_code == 200
                )
                current = http.get(BASE + "/sandboxes").json()["sandboxes"][0]
                assert (
                    current["uid"] == original["uid"]
                    and current["state"] == original["state"]
                )
                ws.send(json.dumps({"type": "input", "data": "still connected"}))
                opcode, data = ws.recv_data(control_frame=True)
                assert (
                    opcode == websocket.ABNF.OPCODE_CLOSE
                    and int.from_bytes(data[:2], "big") == 1012
                )
                assert hook.wait(timeout=5) == 0
                process.send_signal(signal.SIGTERM)
                assert process.wait(timeout=10) in {0, -signal.SIGTERM}
                log.seek(0)
                assert "Application shutdown complete" in log.read()
                log.seek(0)
                assert (
                    "Waiting 3 seconds for user terminal sessions to drain"
                    in log.read()
                )
                assert Path(
                    env["PORTAL_DRAIN_TEST_AUDIT"]
                ).read_text().splitlines() == ["input", "close"]
        finally:
            if ws:
                ws.close()
            for child in [hook, process]:
                if child and child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
