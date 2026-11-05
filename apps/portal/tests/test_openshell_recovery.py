"""Observe accepted outcomes with portal-owned IDs and untracked native calls."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from openshell._proto import openshell_pb2 as pb
from test_openshell import runtime_class, setup_store  # noqa: F401
from test_portal import OWNER
from test_storage import database as database_fixture

from portal.integrations.openshell.client import Gateway
from portal.namespaces import UserNamespaces
from portal.sandboxes import Store
from portal.storage import Conflict, open_store

database = database_fixture


@pytest.mark.parametrize(
    "mode,phase",
    [
        ("Running", pb.SANDBOX_PHASE_READY),
        ("Running", pb.SANDBOX_PHASE_STARTING),
        ("Suspended", pb.SANDBOX_PHASE_STOPPED),
        ("Suspended", pb.SANDBOX_PHASE_STOPPING),
    ],
)
def test_lost_response_recovers_accepted_transition_without_replay(mode, phase):
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    if mode == "Running":
        store.mode(sandbox.name, OWNER, "Suspended")
    method = "StartSandbox" if mode == "Running" else "StopSandbox"
    original = getattr(native, method)

    def lost_response(request, **kwargs):
        original(request, **kwargs)
        native.sandboxes[(sandbox.scope, sandbox.name)].status.phase = phase
        raise HTTPException(504, "response lost")

    setattr(native, method, lost_response)
    with pytest.raises(HTTPException, match="response lost"):
        store.mode(sandbox.name, OWNER, mode)
    blocked = Mock(side_effect=AssertionError("must not replay confirmed work"))
    setattr(native, method, blocked)
    recovered = store.retry(sandbox.name, OWNER)
    assert recovered.record.operation is None
    assert recovered.requested_mode == mode
    assert recovered.record.profile_snapshot == sandbox.record.profile_snapshot
    blocked.assert_not_called()


def test_lost_delete_ack_waits_for_absence_without_replaying_delete():
    _, store, kube, native = setup_store()
    sandbox = store.create(OWNER)
    key = (sandbox.scope, sandbox.name)

    def lost_response(request, **kwargs):
        native.calls.append(("delete", request))
        native.sandboxes[key].status.phase = pb.SANDBOX_PHASE_DELETING
        raise HTTPException(504, "response lost")

    native.DeleteSandbox = lost_response
    with pytest.raises(HTTPException):
        store.delete(sandbox.name, OWNER)
    native.DeleteSandbox = Mock(side_effect=AssertionError("already deleting"))
    assert store.retry(sandbox.name, OWNER).record.operation.kind == "delete"
    assert store.metadata.get_sandbox(sandbox.record.id).resource_usage
    native.DeleteSandbox.assert_not_called()
    del native.sandboxes[key]
    del kube.items[key]
    deleted = store.retry(sandbox.name, OWNER)
    assert deleted.state == "Deleted" and deleted.record.operation is None
    assert not deleted.record.resource_usage


@pytest.mark.parametrize("kind", ["mode", "delete"])
@pytest.mark.parametrize("replacement", ["native-id", "cr-uid", "runtime-identity"])
def test_recovery_never_confirms_a_replacement_allocation(kind, replacement):
    _, store, kube, native = setup_store()
    sandbox = store.create(OWNER)
    store._begin(sandbox, kind, sandbox.record.manifest, "Running", OWNER)
    key = (sandbox.scope, sandbox.name)
    if replacement == "native-id":
        native.sandboxes[key].metadata.id = str(uuid4())
    elif replacement == "cr-uid":
        kube.items[key]["metadata"]["uid"] = str(uuid4())
    else:
        native.sandboxes[key].metadata.annotations[
            "internal.openshell.ai/compute-runtime-identity"
        ] = "kubernetes://another/another/another"
    native.StartSandbox = Mock(side_effect=AssertionError("foreign allocation"))
    native.DeleteSandbox = Mock(side_effect=AssertionError("foreign allocation"))
    with pytest.raises(HTTPException):
        store.retry(sandbox.name, OWNER)
    assert store.metadata.get_sandbox(sandbox.record.id).operation
    native.StartSandbox.assert_not_called()
    native.DeleteSandbox.assert_not_called()


@pytest.mark.parametrize("phase", [pb.SANDBOX_PHASE_COMPLETED, pb.SANDBOX_PHASE_ERROR])
def test_explicit_retry_after_agent_exit_has_no_native_deduplication(phase):
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    store.mode(sandbox.name, OWNER, "Suspended")
    start = native.StartSandbox

    def lost_response(request, **kwargs):
        start(request, **kwargs)
        native.sandboxes[(sandbox.scope, sandbox.name)].status.phase = phase
        raise HTTPException(504, "response lost")

    native.StartSandbox = lost_response
    with pytest.raises(HTTPException):
        store.mode(sandbox.name, OWNER, "Running")
    operation = store.metadata.get_sandbox(sandbox.record.id).operation
    assert operation.request_id
    native.StartSandbox = start
    # Generation-aware recovery is deferred; explicit Retry can start another run.
    assert store.retry(sandbox.name, OWNER).record.operation is None
    assert [r.request_id for k, r in native.calls if k == "start"] == ["", ""]
    assert (
        native.sandboxes[(sandbox.scope, sandbox.name)].status.phase
        == pb.SANDBOX_PHASE_READY
    )


def test_second_replica_recovers_lost_response_after_claim_release(database):
    settings, unused, kube, native = setup_store()
    unused.close()
    metadata = [open_store(database), open_store(database)]
    metadata[0].migrate()
    stores = [
        Store(
            settings,
            custom=kube,
            core=kube,
            namespaces=UserNamespaces(settings, kube, kube, kube),
            metadata=m,
        )
        for m in metadata
    ]
    for store in stores:
        store.integrations.items["openShell"].gateway = Gateway(
            settings.openshell_endpoint, stub=native
        )
    entered, release = threading.Event(), threading.Event()
    stop = native.StopSandbox

    def delayed_lost_response(request, **kwargs):
        stop(request, **kwargs)
        entered.set()
        assert release.wait(10)
        raise HTTPException(504, "response lost")

    native.StopSandbox = delayed_lost_response
    try:
        sandbox = stores[0].create(OWNER)
        with ThreadPoolExecutor(max_workers=1) as workers:
            first = workers.submit(stores[0].mode, sandbox.name, OWNER, "Suspended")
            try:
                assert entered.wait(10)
                with pytest.raises(Conflict, match="already being processed"):
                    stores[1].retry(sandbox.name, OWNER)
                assert metadata[1].get_sandbox(sandbox.record.id).operation
            finally:
                release.set()
            with pytest.raises(HTTPException, match="response lost"):
                first.result(timeout=10)
        recovered = stores[1].retry(sandbox.name, OWNER)
        assert recovered.record.operation is None
        assert recovered.requested_mode == "Suspended"
        assert sum(k == "stop" for k, _ in native.calls) == 1
    finally:
        release.set()
        for store in stores:
            store.close()
        for item in metadata:
            item.close()


def test_all_management_calls_omit_native_ids_with_full_history():
    from test_openshell_policy import update
    from portal.integrations.agent_sandbox.inventory import PREFIX
    from portal.integrations.openshell.policy import REQUEST

    _, store, _, native = setup_store()
    methods = [
        "CreateWorkspace",
        "CreateSandbox",
        "StopSandbox",
        "StartSandbox",
        "UpdateConfig",
        "DeleteSandbox",
    ]
    seen = []
    for method in methods:
        handler = getattr(native, method)

        def full_history(request, *, _method=method, _handler=handler, **kwargs):
            if request.request_id:
                raise HTTPException(429, "durable mutation admission limit reached")
            seen.append(_method)
            return _handler(request, **kwargs)

        setattr(native, method, full_history)
    sandbox = store.create(OWNER)
    key = (sandbox.scope, sandbox.name)
    assert native.sandboxes[key].metadata.annotations[PREFIX + "request-id"]
    store.mode(sandbox.name, OWNER, "Suspended")
    store.mode(sandbox.name, OWNER, "Running")
    assert update(store, sandbox).record.operation is None
    assert native.policies[key].provenance[REQUEST]
    assert store.delete(sandbox.name, OWNER)["status"] == "deleting"
    assert store.metadata.get_sandbox(sandbox.record.id).deleted_at
    assert set(seen) == set(methods)


@pytest.mark.parametrize("kind", ["mode", "delete"])
def test_foreign_native_reply_cannot_complete_the_saved_operation(kind):
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    if kind == "mode":
        result = pb.SandboxResponse(
            sandbox=native.sandboxes[(sandbox.scope, sandbox.name)]
        )
        result.sandbox.metadata.id = str(uuid4())
        native.StopSandbox = Mock(return_value=result)
    else:
        native.DeleteSandbox = Mock(
            return_value=pb.DeleteSandboxResponse(sandbox_id=str(uuid4()))
        )
    with pytest.raises(HTTPException) as error:
        if kind == "mode":
            store.mode(sandbox.name, OWNER, "Suspended")
        else:
            store.delete(sandbox.name, OWNER)
    assert error.value.status_code == 409
    current = store.metadata.get_sandbox(sandbox.record.id)
    assert current.operation and not current.deleted_at
    assert current.binding == sandbox.record.binding
