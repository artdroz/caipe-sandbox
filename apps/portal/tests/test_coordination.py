"""Independent portal processes share claims and recover interrupted native calls."""

import json
import multiprocessing
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import pytest
from test_portal import SETTINGS
from test_storage import database as database
from test_storage import expire_lease, intent

from portal.coordination import claim
from portal.sandboxes import Store
from portal.storage import Conflict, Lease, NativeBinding, StorageError
from portal.storage.schema import leases
from portal.storage.sql import SQLMetadataStore


class RemoteProvider:
    key = "remote"
    provider_instance = "test"

    def __init__(self, endpoint):
        self.endpoint = endpoint

    def find_created(self, manifest, request_id):
        try:
            with urlopen(f"{self.endpoint}/{request_id}", timeout=10) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code == 404:
                return None
            raise

    def create(self, manifest, request_id):
        request = Request(f"{self.endpoint}/{request_id}", data=b"", method="POST")
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def validate_created(self, native, manifest, *, snapshot):
        assert native["id"]

    def binding(self, native):
        return NativeBinding(key=native["id"], reference=native)

    def allocation(self, manifest, *, snapshot=None):
        return None

    def observe(self, binding):
        return SimpleNamespace(
            reference=binding.reference,
            allocation=None,
            state="Running",
            message="Ready",
            requested_mode="Running",
            deleting=False,
        )

    def drift(self, manifest, reference):
        return False

    def close(self):
        pass


def perform_in_process(database, endpoint, sandbox_id, result):
    provider = RemoteProvider(endpoint)
    store = Store(
        replace(SETTINGS, database_url=database.url),
        integrations=SimpleNamespace(
            items={provider.key: provider}, close=provider.close
        ),
    )
    try:
        sandbox = store._perform(store.metadata.get_sandbox(UUID(sandbox_id)))
        result.put(("completed", sandbox.uid))
    except (Conflict, StorageError) as error:
        result.put((type(error).__name__, str(error)))
    finally:
        store.close()


def test_two_processes_exclude_duplicate_dispatch_and_recover_after_kill(database):
    metadata = SQLMetadataStore(database)
    metadata.migrate()
    request_id = uuid4()
    first = metadata.reserve_create(
        intent(provider="remote", profile_snapshot=None), request_id
    )
    second = metadata.reserve_create(
        intent(provider="remote", profile_snapshot=None, name="kind-otter-123ab"),
        uuid4(),
    )
    entered, release = threading.Event(), threading.Event()
    allocations, calls = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            self.send_response(status)
            self.end_headers()
            try:
                self.wfile.write(json.dumps(value).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            native = allocations.get(self.path)
            self.reply(200 if native else 404, native)

        def do_POST(self):
            calls.append(self.path)
            native = allocations.setdefault(self.path, {"id": f"native{self.path}"})
            if self.path == f"/{request_id}":
                entered.set()
                release.wait(20)
            self.reply(200, native)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    context = multiprocessing.get_context("spawn")
    processes, queues = [], []

    def start(record):
        result = context.Queue()
        process = context.Process(
            target=perform_in_process, args=(database, endpoint, str(record.id), result)
        )
        queues.append(result)
        processes.append(process)
        process.start()
        return process, result

    def completed(record):
        process, result = start(record)
        value = result.get(timeout=15)
        process.join(timeout=5)
        assert process.exitcode == 0
        return value

    try:
        blocked, _ = start(first)
        assert entered.wait(15)
        assert completed(first)[0] == "Conflict"
        assert calls == [f"/{request_id}"]
        assert completed(second)[0] == "completed"  # Unrelated sandboxes keep working.
        blocked.terminate()
        blocked.join(timeout=5)
        saved = metadata.get_sandbox(first.id)
        assert saved.binding is None and saved.operation.request_id == request_id
        with metadata.engine.connect() as connection:
            row = (
                connection.execute(
                    leases.select().where(leases.c.name == f"sandbox/{first.id}")
                )
                .mappings()
                .one()
            )
        expire_lease(metadata, Lease.model_validate(row))
        assert completed(first) == ("completed", f"native/{request_id}")
        assert calls.count(f"/{request_id}") == 1
        recovered = metadata.get_sandbox(first.id)
        assert (
            recovered.binding.key == f"native/{request_id}"
            and recovered.operation is None
        )
    finally:
        release.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        for result in queues:
            result.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        metadata.close()


def test_heartbeat_failure_prevents_further_dispatch(database, monkeypatch):
    metadata = SQLMetadataStore(database)
    metadata.migrate()
    attempted = threading.Event()

    def unavailable(*args, **kwargs):
        attempted.set()
        raise StorageError("Metadata database is unavailable")

    try:
        with claim(metadata, "operation", seconds=3) as owner:
            monkeypatch.setattr(metadata, "renew_lease", unavailable)
            assert attempted.wait(5)
            assert owner.lost.wait(1)
            with pytest.raises(Conflict, match="ownership was lost"):
                owner.check()
    finally:
        metadata.close()


def test_heartbeat_renews_ownership_while_provider_call_is_blocked(
    database, monkeypatch
):
    metadata = SQLMetadataStore(database)
    metadata.migrate()
    renewed = threading.Event()
    renew = metadata.renew_lease

    def heartbeat(*args, **kwargs):
        result = renew(*args, **kwargs)
        renewed.set()
        return result

    monkeypatch.setattr(metadata, "renew_lease", heartbeat)
    try:
        with claim(metadata, "operation", seconds=3) as owner:
            assert renewed.wait(5)
            with metadata.engine.connect() as connection:
                expiry = (
                    connection.execute(leases.select()).mappings().one()["expires_at"]
                )
            assert (
                expiry.replace(tzinfo=owner.lease.expires_at.tzinfo)
                > owner.lease.expires_at
            )
            assert metadata.acquire_lease("operation", seconds=3) is None
        assert metadata.acquire_lease("operation", seconds=3)
    finally:
        metadata.close()
