"""In-memory native gateway for tests and the loopback UI preview."""

import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from google.protobuf.json_format import MessageToDict
from openshell._proto import openshell_pb2 as pb
from openshell._proto import sandbox_pb2 as spb
from test_portal import Kubernetes


class Cluster(Kubernetes):
    create_namespaced_limit_range = Kubernetes.create_baseline

    def read_namespaced_limit_range(self, name, namespace):
        return self.read_baseline("LimitRange", name, namespace)

    def list_cluster_custom_object(self, *args, **kwargs):
        return {"items": list(self.items.values())}


class Native:
    def __init__(self, kube):
        self.kube = kube
        self.workspaces = {}
        self.sandboxes = {}
        self.calls = []
        self.create_calls = 0
        self.policies = {}
        self.auto_load = True
        self.global_policy = False

    def GetWorkspace(self, request, **kwargs):
        if request.name not in self.workspaces:
            raise HTTPException(404, "missing")
        return SimpleNamespace(workspace=self.workspaces[request.name])

    def CreateWorkspace(self, request, **kwargs):
        workspace = SimpleNamespace(
            metadata=SimpleNamespace(labels=dict(request.labels))
        )
        self.workspaces[request.name] = workspace
        return SimpleNamespace(workspace=workspace)

    def CreateSandbox(self, request, **kwargs):
        self.create_calls += 1
        namespace = request.workspace_scope.workspace
        native_id = str(uuid4())
        resources = MessageToDict(request.spec.template.resources)
        cr = self.kube.create_namespaced_custom_object(
            "agents.x-k8s.io",
            "v1beta1",
            namespace,
            "sandboxes",
            {
                "apiVersion": "agents.x-k8s.io/v1beta1",
                "kind": "Sandbox",
                "metadata": {
                    "name": request.name,
                    "namespace": namespace,
                    "labels": {
                        "openshell.ai/managed-by": "openshell",
                        "openshell.ai/gateway-id": "gateway",
                        "openshell.ai/sandbox-id": native_id,
                    },
                },
                "spec": {
                    "operatingMode": "Running",
                    "podTemplate": {
                        "spec": {
                            "runtimeClassName": "kata-dev",
                            "containers": [{"name": "agent", "resources": resources}],
                        }
                    },
                    "volumeClaimTemplates": [
                        {
                            "metadata": {"name": "workspace"},
                            "spec": {"resources": {"requests": {"storage": "20Gi"}}},
                        }
                    ],
                },
                "status": {
                    "conditions": [
                        {"type": "Ready", "status": "True", "observedGeneration": 1}
                    ]
                },
            },
        )
        annotations = {
            **request.annotations,
            "internal.openshell.ai/compute-runtime-identity": f"kubernetes://{namespace}/{cr['metadata']['uid']}/supervisor-uid-{request.name}",
        }
        sandbox = pb.Sandbox(
            metadata={
                "id": native_id,
                "name": request.name,
                "workspace": namespace,
                "labels": dict(request.labels),
                "annotations": annotations,
                "resource_version": 1,
            },
            spec=request.spec,
            status={
                "phase": pb.SANDBOX_PHASE_READY,
                "current_policy_version": 1,
                "configuration_admission": {
                    "instance_id": "supervisor-instance",
                    "state": pb.CONFIGURATION_ADMISSION_STATE_ACCEPTED,
                    "policy_version": 1,
                    "policy_hash": "abc",
                },
            },
        )
        self.sandboxes[(namespace, request.name)] = sandbox
        self.policies[(namespace, request.name)] = pb.SandboxPolicyRevision(
            version=1,
            policy_hash="abc",
            status=pb.POLICY_STATUS_LOADED,
            policy=request.spec.policy,
        )
        return pb.SandboxResponse(sandbox=sandbox)

    def GetSandbox(self, request, **kwargs):
        self.calls.append(("get", request))
        try:
            return pb.SandboxResponse(
                sandbox=self.sandboxes[
                    (request.workspace_scope.workspace, request.name)
                ]
            )
        except KeyError:
            raise HTTPException(404, "missing") from None

    def ListSandboxes(self, request, **kwargs):
        labels = dict(x.split("=", 1) for x in request.label_selector.split(","))
        return pb.ListSandboxesResponse(
            sandboxes=[
                s
                for s in self.sandboxes.values()
                if all(s.metadata.labels.get(k) == v for k, v in labels.items())
            ]
        )

    def GetSandboxConfig(self, request, **kwargs):
        revision = self.policies[(request.workspace_scope.workspace, request.name)]
        return spb.GetSandboxConfigResponse(
            policy=revision.policy,
            version=revision.version,
            policy_hash=revision.policy_hash,
            policy_source=spb.POLICY_SOURCE_GLOBAL
            if self.global_policy
            else spb.POLICY_SOURCE_SANDBOX,
            configuration_admitted=True,
            configuration_instance_id="supervisor-instance",
        )

    def GetSandboxPolicyStatus(self, request, **kwargs):
        key = (request.workspace_scope.workspace, request.sandbox)
        return pb.GetSandboxPolicyStatusResponse(
            revision=self.policies[key],
            active_version=self.sandboxes[key].status.current_policy_version,
        )

    def UpdateConfig(self, request, **kwargs):
        self.calls.append(("policy", request))
        key = (request.workspace_scope.workspace, request.sandbox)
        sandbox = self.sandboxes[key]
        if (
            self.global_policy
            or request.expected_resource_version != sandbox.metadata.resource_version
        ):
            raise HTTPException(409, "Native revision conflict")
        revision = pb.SandboxPolicyRevision(
            version=self.policies[key].version + 1,
            policy_hash=str(uuid4()),
            policy=request.policy,
            provenance=request.annotations,
            status=pb.POLICY_STATUS_LOADED
            if self.auto_load
            else pb.POLICY_STATUS_PENDING,
        )
        self.policies[key] = revision
        sandbox.metadata.resource_version += 1
        if self.auto_load:
            self.load_policy(key)
        return pb.UpdateConfigResponse(
            version=revision.version, policy_hash=revision.policy_hash
        )

    def load_policy(self, key):
        revision = self.policies[key]
        revision.status = pb.POLICY_STATUS_LOADED
        sandbox = self.sandboxes[key]
        sandbox.status.current_policy_version = revision.version
        sandbox.status.configuration_admission.policy_version = revision.version
        sandbox.status.configuration_admission.policy_hash = revision.policy_hash

    def StopSandbox(self, request, **kwargs):
        self.calls.append(("stop", request))
        sandbox = self.sandboxes[(request.workspace_scope.workspace, request.name)]
        sandbox.status.phase = pb.SANDBOX_PHASE_STOPPED
        self.kube.items[(request.workspace_scope.workspace, request.name)]["spec"][
            "operatingMode"
        ] = "Suspended"
        return pb.SandboxResponse(sandbox=sandbox)

    def StartSandbox(self, request, **kwargs):
        self.calls.append(("start", request))
        sandbox = self.sandboxes[(request.workspace_scope.workspace, request.name)]
        sandbox.status.phase = pb.SANDBOX_PHASE_READY
        self.kube.items[(request.workspace_scope.workspace, request.name)]["spec"][
            "operatingMode"
        ] = "Running"
        return pb.SandboxResponse(sandbox=sandbox)

    def DeleteSandbox(self, request, **kwargs):
        self.calls.append(("delete", request))
        del self.sandboxes[(request.workspace_scope.workspace, request.name)]
        del self.kube.items[(request.workspace_scope.workspace, request.name)]
        return pb.DeleteSandboxResponse()


class EchoStream:
    """Simulated PTY; never executes commands from a browser."""

    def __init__(self, messages):
        self.messages = iter(messages)
        self.cancelled = False
        self.start = None

    def initial_metadata(self):
        self.start = next(self.messages).start
        return ()

    def cancel(self):
        self.cancelled = True
        return True

    def __iter__(self):
        command = list(self.start.command)
        if command == ["/usr/local/bin/sandbox-control"]:
            body = json.loads(next(self.messages).stdin)
            payload = (
                {
                    "protocol_version": 1,
                    "files": {"startup": [], "service": []},
                    "services": [],
                    "startup": [],
                    "service_errors": [],
                }
                if body["action"] == "inspect"
                else {"saved": True}
            )
            yield pb.ExecSandboxEvent(stdout={"data": json.dumps(payload).encode()})
        elif self.start.tty and "-c" not in command:
            yield pb.ExecSandboxEvent(
                stdout={"data": b"Mock protected terminal - no commands execute.\r\n$ "}
            )
            for message in self.messages:
                if self.cancelled:
                    break
                if message.HasField("stdin"):
                    if message.stdin.strip() == b"exit":
                        break
                    yield pb.ExecSandboxEvent(
                        stdout={
                            "data": message.stdin.replace(b"\r", b"\r\n")
                            + (
                                b"$ "
                                if b"\r" in message.stdin or b"\n" in message.stdin
                                else b""
                            )
                        }
                    )
        else:
            yield pb.ExecSandboxEvent(
                stdout={
                    "data": b"Mock helper completed.\r\n"
                    if self.start.tty
                    else b'{"loggedIn":true}'
                }
            )
        yield pb.ExecSandboxEvent(exit={"exit_code": 0})


def interactive(self, messages, **kwargs):
    stream = EchoStream(messages)
    self.calls.append(("exec", stream))
    return stream


Native.ExecSandboxInteractive = interactive
