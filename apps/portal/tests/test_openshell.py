"""Native service contracts, ownership, uncertain creates and protected routing."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import grpc
import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient
from inventory_fakes import as_sandbox
from openshell._proto import openshell_pb2 as pb
from openshell_fakes import Cluster, EchoStream, Native
from test_portal import BASE, HEADERS, OTHER, OWNER, SETTINGS, Omnigent

from portal.app import create_app
from portal.integrations.agent_sandbox.inventory import PREFIX
from portal.integrations.openshell.client import Gateway
from portal.integrations.openshell.client import failure
from portal.namespaces import UserNamespaces
from portal.profiles import Profiles, applied
from portal.sandboxes import Store
from portal.storage import Conflict


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        (
            "RuntimeClass kata-dev lacks openshell.ai/sandbox-attachable=true",
            "approved by the platform",
        ),
        (
            "request is admitted but has no confirmed replayable success; reconcile effects before starting a new request",
            "administrator must check for partially created resources",
        ),
    ],
)
def test_gateway_precondition_explains_the_required_recovery(detail, expected):
    error = Mock(spec=["code", "details"])
    error.code.return_value = grpc.StatusCode.FAILED_PRECONDITION
    error.details.return_value = detail
    result = failure(error)
    assert result.status_code == 409
    assert expected in result.detail
    assert "FAILED_PRECONDITION" in result.detail


def test_unknown_gateway_details_are_not_exposed():
    error = Mock(spec=["code", "details"])
    error.code.return_value = grpc.StatusCode.INTERNAL
    error.details.return_value = "postgresql://private-credentials@gateway-db"
    assert "private-credentials" not in failure(error).detail


def test_gateway_saved_request_limit_is_distinct_from_compute_capacity():
    error = Mock(spec=["code", "details"])
    error.code.return_value = grpc.StatusCode.RESOURCE_EXHAUSTED
    error.details.return_value = (
        "caller has reached the durable mutation admission limit; "
        "unresolved requests require reconciliation"
    )
    result = failure(error)
    assert result.status_code == 429
    assert "saved action history is full" in result.detail
    assert "platform administrator" in result.detail
    assert "capacity limit" not in result.detail
    error.details.return_value = "worker capacity exceeded"
    assert "capacity limit" in failure(error).detail


@pytest.fixture(autouse=True)
def runtime_class(monkeypatch):
    from kubernetes import client

    monkeypatch.setattr(
        client,
        "NodeV1Api",
        lambda *args: SimpleNamespace(
            read_runtime_class=lambda name, **kwargs: {
                "overhead": {"podFixed": {"cpu": "250m", "memory": "256Mi"}}
            }
        ),
    )


def setup_store(**overrides):
    from pathlib import Path

    values = yaml.safe_load(
        (Path(__file__).parents[1] / "examples/openshell.values.yaml").read_text()
    )
    settings = replace(
        SETTINGS,
        profiles=json.dumps(values["profiles"]),
        default_profile=values["defaultProfile"],
        openshell_endpoint="https://gateway:8080",
        openshell_supervisor_resources=json.dumps(
            values["settings"]["openShell"]["supervisorResources"]
        ),
        openshell_gateway_id="gateway",
        openshell_gateway_service_account="gateway",
        openshell_runner_service_account="openshell-runner",
    )
    settings = replace(settings, **overrides)
    kube = Cluster()
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    native = Native(kube)
    store.integrations.items["openShell"].gateway = Gateway(
        settings.openshell_endpoint, stub=native
    )
    return settings, store, kube, native


def test_native_create_keeps_profile_choices_and_namespace_fencing():
    settings, store, kube, native = setup_store()
    nonce = uuid4()
    cr = store.create(OWNER, request_id=nonce).reference
    assert native.create_calls == 1
    from portal.names import sandbox_name

    assert cr["metadata"]["name"] == sandbox_name(nonce)
    assert len(cr["metadata"]["namespace"]) <= 19
    assert len(cr["metadata"]["name"]) <= 16
    assert cr["metadata"]["annotations"][PREFIX + "owner"] == OWNER
    assert (
        applied(as_sandbox(store, cr))["definition"]["openShell"]["spec"]["policy"][
            "landlock"
        ]["compatibility"]
        == "hard_requirement"
    )
    assert (
        cr["spec"]["podTemplate"]["spec"]["containers"][0]["resources"]["requests"][
            "cpu"
        ]
        == "500m"
    )
    assert (
        cr["spec"]["podTemplate"]["spec"]["containers"][0]["resources"]["limits"]["cpu"]
        == "2000m"
    )
    policy = kube.baseline[
        ("NetworkPolicy", cr["metadata"]["namespace"], "sandbox-isolation")
    ]
    assert policy["spec"]["egress"] == []
    assert (
        kube.namespace_objects[cr["metadata"]["namespace"]]["metadata"]["labels"][
            settings.openshell_namespace_label
        ]
        == "true"
    )
    assert (
        store.create(OWNER, request_id=nonce).reference["metadata"]["uid"]
        == cr["metadata"]["uid"]
    )
    assert native.create_calls == 1


def test_disabled_baseline_keeps_openshell_ssh_connectivity_policy():
    _, store, kube, _ = setup_store(
        namespace_policy=json.dumps(
            {**json.loads(SETTINGS.namespace_policy), "baselineNetworkPolicy": False}
        )
    )
    sandbox = store.create(OWNER).reference
    namespace = sandbox["metadata"]["namespace"]
    assert ("NetworkPolicy", namespace, "sandbox-isolation") not in kube.baseline
    ssh = kube.baseline[("NetworkPolicy", namespace, "openshell-sandbox-ssh")]
    assert ssh["spec"]["policyTypes"] == ["Ingress"]
    assert ssh["spec"]["ingress"][0]["ports"] == [{"protocol": "TCP", "port": 2222}]


def test_default_openshell_runtime_does_not_read_a_runtime_class(monkeypatch):
    from kubernetes import client

    settings, store, _, _ = setup_store(
        runtime_class="", allowed_runtime_classes='[""]'
    )
    profiles = Profiles(settings)
    profile = profiles.get(settings.default_profile)
    spec = profiles.render(profile, profiles.size(profile))
    assert spec["template"]["runtime_class_name"] == ""
    api = Mock()
    monkeypatch.setattr(client, "NodeV1Api", api)
    assert store.integrations.items["openShell"].runtime_overhead("") == {}
    api.assert_not_called()


def test_runtime_status_preserves_badges_from_other_layers():
    _, store, _, _ = setup_store()
    sandbox = store.create(OWNER)
    row = sandbox.view()
    row["integrations"] = [
        {"id": "egress", "title": "Egress", "layer": "Network", "state": "configured"}
    ]
    result = store.integrations.for_sandbox(sandbox).status(sandbox.reference, row)
    assert [badge["id"] for badge in result["integrations"]] == ["egress", "openshell"]
    assert result["integrations"][1]["state"] == "active"
    assert result["integrations"][1]["layer"] == "Runtime"
    assert "protection" not in result


def test_native_lifecycle_uses_gateway_and_keeps_applied_snapshot():
    _, store, _, native = setup_store()
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    assert (
        store.status_view(as_sandbox(store, cr))["integrations"][0]["state"] == "active"
    )
    assert (
        store.mode(name, OWNER, "Suspended").reference["spec"]["operatingMode"]
        == "Suspended"
    )
    assert (
        store.mode(name, OWNER, "Running").reference["metadata"]["uid"]
        == cr["metadata"]["uid"]
    )
    with pytest.raises(HTTPException, match="recreation"):
        store.configure(
            name, OWNER, store.profiles.size(store.profiles.get())
        ).reference
    assert store.delete(name, OWNER)["status"] == "deleting"
    assert [
        name for name, _ in native.calls if name in {"start", "stop", "delete"}
    ] == ["stop", "start", "delete"]


def test_uncertain_create_recovers_metadata_without_reprovisioning():
    _, store, kube, native = setup_store()
    nonce = uuid4()
    cr = store.create(OWNER, request_id=nonce).reference
    original = kube.items[(cr["metadata"]["namespace"], cr["metadata"]["name"])]
    original["metadata"]["annotations"] = {}
    original["metadata"]["labels"] = {
        k: v
        for k, v in original["metadata"]["labels"].items()
        if k.startswith("openshell.ai/")
    }
    recovered = store.create(OWNER, request_id=nonce).reference
    assert recovered["metadata"]["uid"] == cr["metadata"]["uid"]
    assert native.create_calls == 1


def test_owner_and_sharing_checks_happen_before_protected_exec():
    settings, store, _, _ = setup_store()
    cr = store.create(OWNER).reference
    execute = Mock()
    store.integrations.items["openShell"].connect = execute
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        path = BASE + f"/sandboxes/{cr['metadata']['name']}/tools?owner={OWNER}"
        headers = {**HEADERS, "Cookie": "session=bob"}
        assert browser.get(path, headers=headers).status_code == 404
        execute.assert_not_called()
        store.sharing(cr["metadata"]["name"], OWNER, {OTHER: "view"}).reference
        assert browser.get(path, headers=headers).status_code == 404
        execute.assert_not_called()


@pytest.mark.parametrize("change", ["native-id", "runtime-identity", "gateway"])
def test_replaced_or_foreign_native_identity_never_opens_exec(change):
    _, store, kube, native = setup_store()
    cr = store.create(OWNER).reference
    key = (cr["metadata"]["namespace"], cr["metadata"]["name"])
    if change == "native-id":
        native.sandboxes[key].metadata.id = str(uuid4())
    elif change == "runtime-identity":
        native.sandboxes[key].metadata.annotations[
            "internal.openshell.ai/compute-runtime-identity"
        ] = "kubernetes://other/other/pod"
    else:
        kube.items[key]["metadata"]["labels"]["openshell.ai/gateway-id"] = "other"
    with pytest.raises(HTTPException):
        store.execution(key[1], OWNER)


def test_pending_policy_and_gateway_outage_fail_closed():
    _, store, _, native = setup_store()
    cr = store.create(OWNER).reference
    native.sandboxes[
        (cr["metadata"]["namespace"], cr["metadata"]["name"])
    ].status.configuration_admission.state = pb.CONFIGURATION_ADMISSION_STATE_PENDING
    assert store.status_view(as_sandbox(store, cr))["state"] == "Provisioning"
    with pytest.raises(HTTPException, match="not ready"):
        store.execution(cr["metadata"]["name"], OWNER)
    store.integrations.items["openShell"].gateway.get = Mock(
        side_effect=HTTPException(503, "gateway down")
    )
    assert (
        store.status_view(as_sandbox(store, cr))["integrations"][0]["state"]
        == "unknown"
    )
    with pytest.raises(HTTPException):
        store.execution(cr["metadata"]["name"], OWNER)


def test_gateway_outage_does_not_couple_direct_profile_creation():
    settings, store, _, native = setup_store()
    definitions = json.loads(settings.profiles) + json.loads(SETTINGS.profiles)
    store.profiles = Profiles(replace(settings, profiles=json.dumps(definitions)))
    native.GetSandbox = Mock(side_effect=HTTPException(503, "gateway down"))
    cr = store.create(
        OWNER, profile_id=json.loads(SETTINGS.profiles)[0]["id"]
    ).reference
    assert applied(as_sandbox(store, cr))["definition"]["agentSandbox"]
    native.GetSandbox.assert_not_called()
    with pytest.raises(HTTPException):
        store.create(OWNER, profile_id="protected-engineering").reference


def test_profile_cannot_select_both_backends_or_unknown_native_fields():
    settings, store, _, _ = setup_store()
    value = store.profiles.get().model_dump(exclude_none=True)
    value["agentSandbox"] = {"spec": {}}
    with pytest.raises(ValueError, match="exactly one"):
        Profiles(replace(settings, profiles=json.dumps([value])))
    del value["agentSandbox"]
    value["openShell"]["spec"]["unknown_native_option"] = True
    with pytest.raises(ValueError, match="native"):
        Profiles(replace(settings, profiles=json.dumps([value])))


def test_configuration_exposes_native_spec_and_loaded_policy_without_client_credentials():
    _, store, _, _ = setup_store()
    cr = store.create(OWNER).reference
    result = store.configuration(as_sandbox(store, cr))
    assert result["desired"]["apiVersion"] == "openshell.v1"
    assert result["desired"]["spec"]["template"]["runtime_class_name"] == "kata-dev"
    assert result["observed"]["configuration_admission"]["policy_hash"] == "abc"
    assert "tls.key" not in json.dumps(result)


def test_effective_policy_and_admission_follow_gateway_configuration():
    _, store, _, native = setup_store()
    cr = store.create(OWNER).reference
    config = native.GetSandboxConfig(
        SimpleNamespace(
            workspace_scope=SimpleNamespace(workspace=cr["metadata"]["namespace"]),
            name=cr["metadata"]["name"],
        )
    )
    config.policy.filesystem.read_only.append("/global-readonly")
    config.policy_hash = "new-effective-policy"
    native.GetSandboxConfig = Mock(return_value=config)
    result = store.configuration(as_sandbox(store, cr))
    assert (
        "/global-readonly"
        in result["native_configuration"]["spec"]["policy"]["filesystem"]["read_only"]
    )
    assert (
        result["native_configuration"]["configuration"]["policy_hash"]
        == "new-effective-policy"
    )
    assert store.status_view(as_sandbox(store, cr))["state"] == "Provisioning"
    with pytest.raises(HTTPException, match="not ready"):
        store.execution(cr["metadata"]["name"], OWNER)


@pytest.mark.parametrize(
    "field,value",
    [
        ("configuration_admitted", False),
        ("configuration_instance_id", "stale-instance"),
        ("config_revision", 2),
        ("provider_env_revision", 2),
    ],
)
def test_stale_or_unadmitted_configuration_blocks_execution(field, value):
    _, store, _, native = setup_store()
    cr = store.create(OWNER).reference
    config = store.integrations.items["openShell"].config(
        native.sandboxes[(cr["metadata"]["namespace"], cr["metadata"]["name"])]
    )
    setattr(config, field, value)
    native.GetSandboxConfig = Mock(return_value=config)
    assert (
        store.status_view(as_sandbox(store, cr))["integrations"][0]["state"]
        == "pending"
    )
    with pytest.raises(HTTPException, match="not ready"):
        store.execution(cr["metadata"]["name"], OWNER)


def test_generic_execution_never_falls_back_when_protected_transport_fails(monkeypatch):
    from portal.execution import connect
    from portal.integrations.agent_sandbox import execution

    direct = Mock()
    monkeypatch.setattr(execution, "stream", direct)
    from execution_fakes import target

    pod = target(Mock(side_effect=HTTPException(503, "unavailable")))
    with pytest.raises(HTTPException):
        connect(pod, ["bash"])
    direct.assert_not_called()


def test_native_stream_preserves_input_resize_and_cancellation():
    import time

    _, store, _, native = setup_store()
    cr = store.create(OWNER).reference
    connection = store.integrations.items["openShell"].connect(cr, ["/bin/bash", "-i"])
    connection.write_channel(4, json.dumps({"Width": 120, "Height": 40}))
    connection.write_stdin("hello\r")
    output = ""
    deadline = time.monotonic() + 2
    while "hello" not in output and time.monotonic() < deadline:
        connection.update(timeout=0.02)
        output += connection.read_all()
    assert "hello" in output
    stream = [request for name, request in native.calls if name == "exec"][-1]
    assert stream.start.tty is True
    assert not stream.start.request_id
    connection.close()
    assert stream.cancelled


@pytest.mark.parametrize("tty", [True, False])
def test_execution_works_when_durable_mutation_history_is_full(tty):
    class HistoryFull(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.RESOURCE_EXHAUSTED

        def details(self):
            return "caller has reached the durable mutation admission limit"

    class LimitedStream(EchoStream):
        def initial_metadata(self):
            super().initial_metadata()
            if self.start.request_id:
                raise HistoryFull()
            return ()

    stub = Mock()
    stub.ExecSandboxInteractive.side_effect = LimitedStream
    gateway = Gateway("https://gateway:8080", stub=stub)
    connection = gateway.connect("test-namespace", "test-vm", ["bash"], tty=tty)
    try:
        assert connection.started.is_set()
        stub.ExecSandboxInteractive.assert_called_once()
    finally:
        connection.close()


def test_failed_execution_attachment_is_not_automatically_retried():
    class Unavailable(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNAVAILABLE

        def details(self):
            return "response lost"

    stub = Mock()
    stub.ExecSandboxInteractive.side_effect = Unavailable()
    gateway = Gateway("https://gateway:8080", stub=stub)
    with pytest.raises(HTTPException, match="OpenShell is unavailable"):
        gateway.connect("test-namespace", "test-vm", ["bash"])
    stub.ExecSandboxInteractive.assert_called_once()


def test_service_control_uses_the_protected_stream(monkeypatch):
    from portal.integrations.agent_sandbox import execution
    from portal.workspace import Workspace

    _, store, _, _ = setup_store()
    cr = store.create(OWNER).reference
    direct = Mock()
    monkeypatch.setattr(execution, "stream", direct)
    result = Workspace().run(
        store.execution(cr["metadata"]["name"], OWNER), {"action": "inspect"}
    )
    assert result["protocol_version"] == 1
    direct.assert_not_called()


def test_native_quota_counts_supervisor_and_runtimeclass_overhead(monkeypatch):
    from decimal import Decimal

    from kubernetes import client

    resources = {
        "requests": {"cpu": "250m", "memory": "256Mi"},
        "limits": {"cpu": "750m", "memory": "768Mi"},
    }
    _, store, kube, _ = setup_store(
        openshell_supervisor_resources=json.dumps(resources)
    )
    cr = store.create(OWNER).reference
    defaults = kube.baseline[
        ("LimitRange", cr["metadata"]["namespace"], "openshell-defaults")
    ]["spec"]["limits"][0]
    assert defaults["defaultRequest"] == resources["requests"]
    assert defaults["default"] == resources["limits"]
    node = Mock()
    node.read_runtime_class.return_value = {
        "overhead": {"podFixed": {"cpu": "250m", "memory": "320Mi"}}
    }
    monkeypatch.setattr(client, "NodeV1Api", lambda *args: node)
    usage = store.integrations.items["openShell"].usage(cr)
    assert usage["requests.cpu"] == Decimal("1")
    assert usage["limits.cpu"] == Decimal("3")
    assert usage["pods"] == 2
    assert usage["persistentvolumeclaims"] == 1


@pytest.mark.parametrize(
    "resources",
    [
        {},
        {"requests": {"cpu": "100m", "memory": "128Mi"}},
        {
            "requests": {"cpu": "2", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "512Mi"},
        },
        {
            "requests": {"cpu": "-1", "memory": "128Mi"},
            "limits": {"cpu": "1", "memory": "512Mi"},
        },
    ],
)
def test_invalid_operator_supervisor_resources_block_profile_activation(resources):
    with pytest.raises(ValueError, match="supervisorResources"):
        setup_store(openshell_supervisor_resources=json.dumps(resources))


def test_native_landlock_choice_is_owned_by_the_profile():
    _, store, _, _ = setup_store()
    profile = store.profiles.get().model_copy(deep=True)
    profile.openShell.spec["policy"]["landlock"]["compatibility"] = "best_effort"
    rendered = store.profiles.render(profile, store.profiles.size(profile))
    assert rendered["policy"]["landlock"]["compatibility"] == "best_effort"


def test_kubernetes_shutdown_has_time_to_finish(monkeypatch):
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    stop = native.StopSandbox

    def graceful_stop(request, *, timeout):
        if timeout < 35:
            raise HTTPException(504, "Kubernetes is still terminating the Pods")
        return stop(request, timeout=timeout)

    monkeypatch.setattr(native, "StopSandbox", graceful_stop)
    current = store.mode(sandbox.name, OWNER, "Suspended")
    assert current.record.operation is None
    assert current.requested_mode == "Suspended"


def test_uncertain_gateway_operation_keeps_portal_id_without_native_replay(monkeypatch):
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    backend = store.integrations.items["openShell"]
    dispatch = Mock(wraps=backend.mode)
    monkeypatch.setattr(backend, "mode", dispatch)
    stop = native.StopSandbox

    def lost_response(request, **kwargs):
        native.calls.append(("stop", request))
        raise HTTPException(504, "response lost")

    monkeypatch.setattr(native, "StopSandbox", lost_response)
    with pytest.raises(HTTPException):
        store.mode(sandbox.name, OWNER, "Suspended")
    pending = store.get(sandbox.name, OWNER).record.operation
    assert pending.kind == "mode"
    monkeypatch.setattr(native, "StopSandbox", stop)
    assert store.retry(sandbox.name, OWNER).record.operation is None
    keys = [request.request_id for kind, request in native.calls if kind == "stop"]
    assert keys == ["", ""]
    assert [call.kwargs["request_id"] for call in dispatch.call_args_list] == [
        pending.request_id,
        pending.request_id,
    ]
    assert sandbox.record.binding.reference["sandbox_id"]
    assert sandbox.record.binding.reference["gateway_id"] == "gateway"


def test_gateway_outage_keeps_the_integration_badge_without_claiming_health():
    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    native.GetSandbox = Mock(side_effect=HTTPException(503, "unavailable"))
    row = store.status_view(store.get(sandbox.name, OWNER))
    assert row["state"] == "Unknown"
    assert row["integrations"][0]["id"] == "openshell"
    assert row["integrations"][0]["state"] == "unknown"


@pytest.mark.parametrize("mode", ["perUser", "perSandbox"])
def test_openshell_honors_namespace_placement_and_shares_only_its_scope(mode):
    settings, store, kube, native = setup_store(
        namespace=json.dumps(
            {"strategy": "perSandbox", "allowedStrategies": ["perUser", "perSandbox"]}
        )
    )
    first = store.create(OWNER, namespace_strategy=mode)
    second = store.create(OWNER, namespace_strategy=mode)
    assert (first.scope == second.scope) == (mode == "perUser")
    assert len(native.workspaces) == (1 if mode == "perUser" else 2)
    assert (
        kube.namespace_objects[first.scope]["metadata"]["labels"][
            PREFIX + "namespace-strategy"
        ]
        == mode
    )
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    assert store.shared_get(first.name, OTHER, OWNER, shell=True).scope == first.scope
    if mode == "perUser":
        assert (
            store.shared_get(second.name, OTHER, OWNER, shell=True).scope == first.scope
        )
    else:
        with pytest.raises(HTTPException):
            store.shared_get(second.name, OTHER, OWNER)


def test_openshell_namespace_keeps_first_owner_when_another_engineer_creates_inside_it():
    settings, store, kube, native = setup_store(
        namespace='{"strategy":"perSandbox","allowedStrategies":["perSandbox","perUser"]}'
    )
    first = store.create(OWNER)
    store.sharing(first.name, OWNER, {OTHER: "shell"})
    second = store.create(OTHER, namespace=first.scope)
    assert second.owner == OTHER and second.record.scope_owner == OWNER
    assert first.scope == second.scope and len(native.workspaces) == 1
    assert store.namespace_access.list(OTHER)[0]["owner"] == OWNER
    assert (
        store.shared_get(str(second.record.id), OWNER, OWNER, shell=True).owner == OTHER
    )
    with pytest.raises(HTTPException):
        store.mode(str(second.record.id), OWNER, "Suspended")
    key = (second.scope, second.name)
    assert (
        native.sandboxes[key].metadata.annotations[PREFIX + "namespace-owner"] == OWNER
    )
    store.settings = replace(
        store.settings,
        namespace_policy=json.dumps(
            {**json.loads(store.settings.namespace_policy), "deleteWhenEmpty": True}
        ),
    )
    store.integrations.catalog.settings = store.settings
    native.DeleteWorkspace = Mock(
        side_effect=lambda request, **kwargs: native.workspaces.pop(request.name)
    )
    kube.delete_namespace = Mock(
        side_effect=lambda name, body: kube.namespace_objects.pop(name)
    )
    store.delete(first.name, OWNER)
    store.cleanup_namespaces()
    assert first.scope in kube.namespace_objects
    store.delete(second.name, OTHER)
    store.cleanup_namespaces()
    assert (
        first.scope not in kube.namespace_objects
        and first.scope not in native.workspaces
    )


def rejected_creation(store, native, monkeypatch):
    from portal.integrations.errors import CreationRejected

    monkeypatch.setattr(
        native,
        "CreateSandbox",
        Mock(side_effect=CreationRejected(409, "Runtime rejected creation")),
    )
    request_id = uuid4()
    with pytest.raises(CreationRejected):
        store.create(OWNER, request_id=request_id)
    return store.metadata.find_creation(OWNER, request_id)


def test_rejected_creation_can_be_cancelled_without_reusing_native_request(monkeypatch):
    _, store, _, native = setup_store()
    record = rejected_creation(store, native, monkeypatch)
    assert store.list(OWNER)[0].view()["operation"]["creation_rejected"]
    with pytest.raises(Conflict, match="Cancel creation"):
        store.retry(record.name, OWNER)
    assert native.CreateSandbox.call_count == 1
    assert store.delete(record.name, OWNER)["status"] == "deleted"
    saved = store.metadata.get_sandbox(record.id)
    assert saved.deleted_at and saved.operation is None and not saved.resource_usage
    assert store.list(OWNER) == []
    with pytest.raises(HTTPException, match="deleted sandbox"):
        store.create(OWNER, request_id=record.operation.request_id)


def test_unknown_creation_outcome_is_not_treated_as_rejected(monkeypatch):
    _, store, _, native = setup_store()
    monkeypatch.setattr(
        native,
        "CreateSandbox",
        Mock(side_effect=HTTPException(504, "Creation timed out")),
    )
    request_id = uuid4()
    with pytest.raises(HTTPException):
        store.create(OWNER, request_id=request_id)
    record = store.metadata.find_creation(OWNER, request_id)
    with pytest.raises(HTTPException, match="outcome is still unknown"):
        store.delete(record.name, OWNER)
    saved = store.metadata.get_sandbox(record.id)
    assert not saved.deleted_at and saved.resource_usage and saved.operation


@pytest.mark.parametrize("resource", ["pod", "supervisor", "disk", "cr", "unavailable"])
def test_cancellation_preserves_reservation_when_cleanup_is_not_proven(
    monkeypatch, resource
):
    from kubernetes.client import ApiException

    _, store, kube, native = setup_store()
    record = rejected_creation(store, native, monkeypatch)
    item = {"metadata": {"name": record.name, "namespace": record.scope}}
    if resource == "supervisor":
        item["metadata"].update(
            name="supervisor",
            ownerReferences=[{"kind": "Sandbox", "name": record.name}],
        )
    if resource in {"pod", "supervisor"}:
        monkeypatch.setattr(
            kube,
            "list_namespaced_pod",
            Mock(return_value=SimpleNamespace(items=[item])),
        )
    elif resource == "disk":
        item["metadata"]["name"] = "workspace-" + record.name
        monkeypatch.setattr(
            kube,
            "list_namespaced_persistent_volume_claim",
            Mock(return_value=SimpleNamespace(items=[item])),
        )
    elif resource == "cr":
        kube.items[(record.scope, record.name)] = item
    else:
        monkeypatch.setattr(
            kube, "list_namespaced_pod", Mock(side_effect=ApiException(status=403))
        )
    with pytest.raises(HTTPException):
        store.delete(record.name, OWNER)
    saved = store.metadata.get_sandbox(record.id)
    assert not saved.deleted_at and saved.resource_usage and saved.operation


def test_cancel_creation_recovers_existing_binding_and_uses_native_delete(monkeypatch):
    _, store, _, native = setup_store()
    create = native.CreateSandbox
    request_id = uuid4()

    def lost_response(request, **kwargs):
        create(request, **kwargs)
        raise HTTPException(504, "Lost create response")

    monkeypatch.setattr(native, "CreateSandbox", lost_response)
    with pytest.raises(HTTPException):
        store.create(OWNER, request_id=request_id)
    record = store.metadata.find_creation(OWNER, request_id)
    assert record.binding is None
    assert store.delete(record.name, OWNER)["status"] == "deleting"
    assert [name for name, _ in native.calls].count("delete") == 1
    assert store.list(OWNER) == []


def test_native_replay_failure_never_claims_the_original_creation_has_finished():
    from portal.integrations.errors import CreationRejected

    error = Mock(spec=["code", "details"])
    error.code.return_value = grpc.StatusCode.FAILED_PRECONDITION
    error.details.return_value = (
        "request is admitted but has no confirmed replayable success"
    )
    result = failure(error, "CreateSandbox")
    assert "Cancel creation" in result.detail
    assert not isinstance(result, CreationRejected)
    error.details.return_value = (
        "RuntimeClass kata-dev lacks openshell.ai/sandbox-attachable=true"
    )
    assert isinstance(failure(error, "CreateSandbox"), CreationRejected)
    assert not isinstance(failure(error, "StopSandbox"), CreationRejected)


def test_cancellation_cannot_race_an_operation_owner(monkeypatch):
    _, store, _, native = setup_store()
    record = rejected_creation(store, native, monkeypatch)
    lease = store.metadata.acquire_lease(f"sandbox/{record.id}", seconds=30)
    try:
        with pytest.raises(Conflict, match="already being processed"):
            store.delete(record.name, OWNER)
        assert not store.metadata.get_sandbox(record.id).deleted_at
    finally:
        store.metadata.release_lease(lease)


def test_cancellation_does_not_remove_other_resources_in_shared_namespace(monkeypatch):
    _, store, kube, native = setup_store()
    record = rejected_creation(store, native, monkeypatch)
    other = {
        "metadata": {
            "name": "another-micro-vm",
            "ownerReferences": [{"kind": "Sandbox", "name": "another-micro-vm"}],
        }
    }
    monkeypatch.setattr(
        kube, "list_namespaced_pod", Mock(return_value=SimpleNamespace(items=[other]))
    )
    monkeypatch.setattr(
        kube,
        "list_namespaced_persistent_volume_claim",
        Mock(return_value=SimpleNamespace(items=[other])),
    )
    delete_namespace = Mock(
        side_effect=AssertionError("Must not delete a shared namespace")
    )
    monkeypatch.setattr(kube, "delete_namespace", delete_namespace, raising=False)
    assert store.delete(record.name, OWNER)["status"] == "deleted"
    delete_namespace.assert_not_called()


def test_execution_keeps_supervisor_identity_separate_from_workload_identity():
    from portal.execution import connect

    _, store, _, native = setup_store()
    sandbox = store.create(OWNER)
    saved = native.sandboxes[(sandbox.scope, sandbox.name)]
    assert saved.metadata.annotations[
        "internal.openshell.ai/compute-runtime-identity"
    ].endswith("/supervisor-uid-" + sandbox.name)
    target = store.execution(sandbox.name, OWNER)
    assert target.key[-1] == "pod-uid-" + sandbox.name
    stream = connect(target, ["/bin/sh"], stdin=False)
    stream.close()
    assert any(name == "exec" for name, _ in native.calls)


@pytest.mark.parametrize("change", ["uid", "owner", "phase", "missing"])
def test_captured_execution_target_rechecks_the_workload_before_connect(
    monkeypatch, change
):
    from portal.execution import connect

    _, store, kube, native = setup_store()
    sandbox = store.create(OWNER)
    target = store.execution(sandbox.name, OWNER)
    pod = kube.read_namespaced_pod(sandbox.name, sandbox.scope)
    if change == "uid":
        pod.metadata.uid = "replacement-workload"
    elif change == "owner":
        pod.metadata.owner_references[0].uid = "different-sandbox"
    elif change == "phase":
        pod.status.phase = "Failed"
    if change == "missing":
        from kubernetes.client import ApiException

        read = Mock(side_effect=ApiException(status=404))
    else:
        read = Mock(return_value=pod)
    monkeypatch.setattr(kube, "read_namespaced_pod", read)
    with pytest.raises(HTTPException):
        connect(target, ["/bin/sh"], stdin=False)
    assert not any(name == "exec" for name, _ in native.calls)
