"""Two real portal processes share PostgreSQL behind a readiness-aware proxy."""

import asyncio
import http.client
import json
import os
import queue
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, closing
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import websocket
from test_drain import Stream
from test_inventory import RemoteProvider
from test_portal import (
    BASE,
    HEADERS,
    OTHER,
    OWNER,
    PROFILE_FIXTURES,
    SETTINGS,
    Omnigent,
)
from test_storage import database as database

from portal.app import create_app
from portal.execution import ExecutionTarget
from portal.integrations import Integrations
from portal.sandboxes import Store
from portal.storage import NativeBinding, SandboxIntent, open_store


def audit(event, **values):
    with Path(os.environ["REPLICA_TEST_AUDIT"]).open("a") as output:
        output.write(json.dumps({"event": event, **values}) + "\n")


def server_app():
    import portal.app as module

    capacity = os.environ.get("PORTAL_CAPACITY_BENCHMARK") == "1"
    module.AUTH_RECHECK_SECONDS = 5 if capacity else 0.05

    class Provider(RemoteProvider):
        def execution(self, reference, *, admin=False):
            def attach(command, **kwargs):
                audit("exec", command=command)

                class Connection(Stream):
                    def __init__(self):
                        super().__init__()
                        self.output = queue.Queue()
                        self.pending = ""

                    def update(self, timeout):
                        if not capacity:
                            return super().update(timeout)
                        try:
                            self.pending = self.output.get(timeout=timeout)
                        except queue.Empty:
                            pass

                    def read_all(self):
                        result, self.pending = self.pending, ""
                        return result

                    def write_stdin(self, data):
                        if capacity:
                            self.output.put(data)
                        else:
                            audit("input", data=data)
                        super().write_stdin(data)

                return Connection()

            return ExecutionTarget(
                key=("remote", reference.identity),
                scope=self.sandbox.scope,
                sandbox_uid=self.sandbox.uid,
                connector=attach,
            )

        def mode(self, *args, **kwargs):
            audit("mode")
            raise AssertionError("A portal restart must not change native compute")

        def delete(self, *args, **kwargs):
            audit("delete")
            raise AssertionError("A portal restart must not delete native compute")

    registry = object.__new__(Integrations)
    registry.items = {"remote": Provider()}
    settings = replace(
        SETTINGS,
        database_url=os.environ["PORTAL_DATABASE_URL"],
        database_backend="postgresql",
        drain_file=os.environ["PORTAL_DRAIN_FILE"],
        drain_seconds=3,
        drain_propagation_seconds=0,
        terminal_io_workers=int(
            os.environ.get("PORTAL_TERMINAL_IO_WORKERS", SETTINGS.terminal_io_workers)
        ),
    )
    store = Store(settings, integrations=registry)
    app = create_app(settings, store, Omnigent())
    if capacity:

        @app.get("/_test/capacity", include_in_schema=False)
        async def capacity_metrics():
            import resource

            queued = time.perf_counter()
            queue_wait = await asyncio.to_thread(lambda: time.perf_counter() - queued)
            terminal_queued = time.perf_counter()
            terminal_wait = await app.state.terminal_io.run(
                lambda: time.perf_counter() - terminal_queued
            )
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return {
                "management_queue_wait_seconds": queue_wait,
                "terminal_queue_wait_seconds": terminal_wait,
                "terminal_io_workers": settings.terminal_io_workers,
                "cpu_seconds": usage.ru_utime + usage.ru_stime,
                "peak_rss_bytes": usage.ru_maxrss
                * (1 if sys.platform == "darwin" else 1024),
                "threads": threading.active_count(),
                "pool_size": store.metadata.engine.pool.size(),
                "checked_out": store.metadata.engine.pool.checkedout(),
            }

    return app


def wait_until(check, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.03)
    pytest.fail("Replica acceptance condition timed out")


def ready(port):
    try:
        with closing(
            http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
        ) as connection:
            connection.request("GET", "/readyz")
            return connection.getresponse().status == 200
    except OSError:
        return False


class Proxy(BaseHTTPRequestHandler):
    """Test-only HTTP/opaque WebSocket forwarding; every new request checks readiness."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        with self.server.lock:
            candidates = [port for port in self.server.backends if ready(port)]
            if not candidates:
                self.send_error(503)
                return
            port = candidates[self.server.cursor % len(candidates)]
            self.server.cursor += 1
        with socket.create_connection(("127.0.0.1", port), timeout=2) as upstream:
            upstream.sendall(
                (
                    f"{self.command} {self.path} HTTP/1.1\r\n"
                    + "".join(
                        f"{key}: {value}\r\n" for key, value in self.headers.items()
                    )
                    + "\r\n"
                ).encode()
            )
            length = int(self.headers.get("Content-Length", 0))
            if length:
                upstream.sendall(self.rfile.read(length))
            head = b""
            while b"\r\n\r\n" not in head:
                block = upstream.recv(4096)
                if not block:
                    return
                head += block
                assert len(head) < 65536
            headers, body = head.split(b"\r\n\r\n", 1)
            self.connection.sendall(
                headers + f"\r\nX-Test-Replica: {port}\r\n\r\n".encode() + body
            )
            upstream.settimeout(None)
            while not self.server.stopping.is_set():
                readable, _, _ = select.select([upstream, self.connection], [], [], 0.1)
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (self.connection if source is upstream else upstream).sendall(data)

    do_PUT = do_GET


@pytest.fixture
def replicas(database, tmp_path):
    if database.parsed_url().get_backend_name() != "postgresql":
        pytest.skip("Replica acceptance requires real PostgreSQL")
    with ExitStack() as stack:
        metadata = open_store(database)
        stack.callback(metadata.close)
        metadata.migrate()
        record = metadata.reserve_create(
            SandboxIntent(
                id=uuid4(),
                name="calm-fox",
                owner=OWNER,
                scope="team/project",
                provider="remote",
                provider_instance=RemoteProvider.provider_instance,
                manifest={"instance": "remote-allocation-42"},
                profile_snapshot={
                    "id": "development",
                    "revision": "sha256:" + "0" * 64,
                    "definition": PROFILE_FIXTURES[0],
                    "namespaceStrategy": "perUser",
                },
            ),
            uuid4(),
        )
        bound = metadata.confirm_binding(
            record.id,
            NativeBinding(key="remote-42", reference={"id": "remote-allocation-42"}),
            expected_revision=record.revision,
        )
        metadata.set_scope_grants(
            record.id, {OTHER: "shell"}, expected_revision=bound.revision
        )
        audit_path = tmp_path / "audit.jsonl"
        children, ports, environments = [], [], []

        def start(index=None):
            if index is None:
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    ports.append(reservation.getsockname()[1])
                index = len(ports) - 1
                environments.append(
                    {
                        **os.environ,
                        "PYTHONPATH": os.pathsep.join(
                            [str(Path(__file__).parent), str(Path(__file__).parents[1])]
                        ),
                        "PORTAL_DATABASE_URL": database.url,
                        "PORTAL_DRAIN_FILE": str(tmp_path / f"drain-{index}"),
                        "PORTAL_DRAIN_SECONDS": "3",
                        "PORTAL_DRAIN_PROPAGATION_SECONDS": "0",
                        "REPLICA_TEST_AUDIT": str(audit_path),
                    }
                )
            log = stack.enter_context((tmp_path / f"server-{index}.log").open("a"))
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "test_replicas:server_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(ports[index]),
                    "--timeout-graceful-shutdown",
                    "2",
                    "--no-access-log",
                ],
                env=environments[index],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            children.append(process)
            wait_until(lambda: ready(ports[index]))
            return process

        def stop_children():
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)

        stack.callback(stop_children)
        first, second = start(), start()
        proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        proxy.daemon_threads = True
        proxy.backends, proxy.cursor, proxy.lock = ports, 0, threading.Lock()
        proxy.stopping = threading.Event()
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()

        def stop_proxy():
            proxy.stopping.set()
            proxy.shutdown()
            proxy.server_close()
            thread.join(timeout=2)

        stack.callback(stop_proxy)
        endpoint = f"127.0.0.1:{proxy.server_port}"
        http = stack.enter_context(
            httpx.Client(base_url=f"http://{endpoint}", headers=HEADERS, timeout=5)
        )

        def terminal(*, helper=False, bob=False):
            query = "?helper=claude-login" if helper else ""
            if bob:
                query = "?owner=" + OWNER
            ws = websocket.create_connection(
                f"ws://{endpoint}{BASE}/sandboxes/calm-fox/terminal{query}",
                origin=SETTINGS.origin,
                cookie="session=bob" if bob else "session=alice",
                timeout=8,
            )
            stack.callback(ws.close)
            assert json.loads(ws.recv())["type"] == "ready"
            return ws

        yield (
            first,
            second,
            start,
            ports,
            environments,
            terminal,
            http,
            metadata,
            record,
            audit_path,
        )


def test_drain_and_replacement_preserve_shared_access_and_native_identity(replicas):
    (
        first,
        _,
        start,
        ports,
        environments,
        terminal,
        http,
        metadata,
        record,
        audit_path,
    ) = replicas
    helper, survivor, owner, _, bob = (
        terminal(helper=True),
        terminal(),
        terminal(),
        terminal(),
        terminal(bob=True),
    )
    assert int(helper.getheaders()["x-test-replica"]) == ports[0]
    assert int(bob.getheaders()["x-test-replica"]) == ports[0]
    hook = subprocess.Popen([sys.executable, "-m", "portal.drain"], env=environments[0])
    try:
        assert json.loads(owner.recv())["type"] == "draining"
        assert json.loads(bob.recv())["type"] == "draining"
        owner.send(json.dumps({"type": "input", "data": "only once"}))
        wait_until(lambda: not ready(ports[0]))
        assert httpx.get(f"http://127.0.0.1:{ports[0]}/healthz").status_code == 200
        response = http.put(BASE + "/sandboxes/calm-fox/sharing", json={"members": {}})
        assert (
            response.status_code == 200
            and int(response.headers["x-test-replica"]) == ports[1]
        )
        assert json.loads(bob.recv())["code"] == "http-404"
        fresh = terminal()
        assert int(fresh.getheaders()["x-test-replica"]) == ports[1]
        assert json.loads(helper.recv())["type"] == "draining"
        for ws in [owner, helper]:
            opcode, data = ws.recv_data(control_frame=True)
            assert (
                opcode == websocket.ABNF.OPCODE_CLOSE
                and int.from_bytes(data[:2], "big") == 1012
            )
        assert hook.wait(timeout=8) == 0
    finally:
        if hook.poll() is None:
            hook.kill()
            hook.wait(timeout=5)
    first.send_signal(signal.SIGTERM)
    assert first.wait(timeout=10) in {0, -signal.SIGTERM}
    start(0)
    assert {int(terminal().getheaders()["x-test-replica"]) for _ in range(2)} == set(
        ports
    )
    survivor.send(json.dumps({"type": "input", "data": "survived"}))
    wait_until(lambda: '"survived"' in audit_path.read_text())
    current = metadata.get_sandbox(record.id)
    assert current.binding.key == "remote-42" and current.manifest == record.manifest
    assert current.grants == {} and current.operation is None
    events = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert sum(e["event"] == "exec" and "-c" in e["command"] for e in events) == 1
    assert sum(e["event"] == "input" and e["data"] == "only once" for e in events) == 1
    assert not any(e["event"] in {"mode", "delete"} for e in events)


def test_abrupt_replica_loss_allows_new_shell_on_survivor(replicas):
    first, _, _, ports, _, terminal, http, metadata, record, audit_path = replicas
    original = terminal()
    assert int(original.getheaders()["x-test-replica"]) == ports[0]
    first.kill()
    first.wait(timeout=10)
    with pytest.raises(websocket.WebSocketConnectionClosedException):
        original.recv()
    replacement = terminal()
    assert int(replacement.getheaders()["x-test-replica"]) == ports[1]
    response = http.get(BASE + "/sandboxes")
    assert response.status_code == 200
    assert response.json()["sandboxes"][0]["portal_id"] == str(record.id)
    assert metadata.get_sandbox(record.id).binding.key == "remote-42"
    assert all(
        json.loads(line)["event"] == "exec"
        for line in audit_path.read_text().splitlines()
    )
