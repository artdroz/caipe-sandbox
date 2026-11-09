"""Loopback-only UI preview with fake Kubernetes/SSO; never used by production."""

import json
import os
import threading
from dataclasses import replace
from http.cookies import SimpleCookie
from pathlib import Path
from uuid import uuid4

import yaml
from fastapi.responses import RedirectResponse
from fastapi import HTTPException
from openshell._proto import openshell_pb2 as pb
from openshell_fakes import Cluster, EchoStream, Native
from preview_workspace import PreviewWorkspace
from test_portal import OWNER, SETTINGS, Omnigent
from test_provisioning import pod_for

from portal.app import IntegrationUpdate, create_app
from portal.controls import GlobalUpdate, SandboxUpdate
from portal.integrations.openshell.client import Execution, Gateway
from portal.integrations.errors import CreationRejected
from portal.integrations.status import IntegrationStatus
from portal.namespaces import UserNamespaces
from portal.resources import Allocation
from portal.sandboxes import Store
from portal.storage import PendingOperation


class PreviewKubernetes(Cluster):
    def create_namespaced_custom_object(self, *args, **kwargs):
        value = super().create_namespaced_custom_object(*args, **kwargs)
        if kwargs.get("dry_run") != "All":
            value.setdefault(
                "status",
                {
                    "conditions": [
                        {
                            "type": "Ready",
                            "status": "True",
                            "observedGeneration": value["metadata"]["generation"],
                        }
                    ]
                },
            )
            self.items[(value["metadata"]["namespace"], value["metadata"]["name"])] = (
                value
            )
        return value

    def delete_namespace(self, name, body):
        del self.namespace_objects[name]
        self.baseline = {
            key: value for key, value in self.baseline.items() if key[1] != name
        }

    def list_cluster_custom_object(self, group, version, plural, limit, _continue):
        return {"items": list(self.items.values())}

    def read_namespaced_pod(self, name, namespace):
        if name == failed["metadata"]["name"]:
            return pod_for(self.items[(namespace, name)], "ImagePullBackOff")
        pod = super().read_namespaced_pod(name, namespace)
        from types import SimpleNamespace

        pod.spec = SimpleNamespace(containers=[SimpleNamespace(name="host")])

        return pod

    def patch_namespaced_custom_object(
        self, group, version, namespace, plural, name, body, **kwargs
    ):
        super().patch_namespaced_custom_object(
            group, version, namespace, plural, name, body
        )
        record = self.items[(namespace, name)]
        if "spec" not in body:
            return record
        kind = (
            "Suspended"
            if record["spec"].get("operatingMode") == "Suspended"
            else "Ready"
        )
        record["status"] = {
            "conditions": [
                {
                    "type": kind,
                    "status": "True",
                    "observedGeneration": record["metadata"]["generation"],
                }
            ]
        }
        return record


definitions = yaml.safe_load(
    (Path(__file__).parents[1] / "examples/engineering.values.yaml").read_text()
)["profiles"]

protected_values = yaml.safe_load(
    (Path(__file__).parents[1] / "examples/openshell.values.yaml").read_text()
)
protected = protected_values["profiles"][0]
protected["openShell"]["spec"]["command"].extend(["--service", "omnigent"])
protected["ui"]["resources"]["default"].update(
    requests={"cpu": "250m", "memory": "512Mi"}, limits={"cpu": "1", "memory": "2Gi"}
)
protected["ui"]["resources"]["minimum"]["storage"] = "5Gi"
protected["ui"]["resources"]["maximum"]["storage"] = "100Gi"
protected["openShell"]["spec"]["environment"]["HOME"] = "/sandbox/home"
definitions.append(protected)

settings = replace(
    SETTINGS,
    namespace='{"strategy":"perSandbox","allowedStrategies":["perSandbox","perUser"]}',
    namespace_policy=json.dumps(
        {**json.loads(SETTINGS.namespace_policy), "deleteWhenEmpty": True}
    ),
    reconcile_interval_seconds=int(
        os.environ.get("PORTAL_RECONCILE_INTERVAL_SECONDS", "30")
    ),
    drain_file=os.environ.get("PORTAL_DRAIN_FILE", "/tmp/portal-preview-drain"),
    drain_seconds=int(os.environ.get("PORTAL_DRAIN_SECONDS", "180")),
    profiles=json.dumps(definitions),
    default_profile="engineering",
    origin=os.environ.get("PORTAL_PREVIEW_ORIGIN", "http://127.0.0.1:4193"),
    admin_emails=json.dumps([OWNER]),
    openshell_endpoint="https://mock-gateway:8080",
    openshell_supervisor_resources=json.dumps(
        protected_values["settings"]["openShell"]["supervisorResources"]
    ),
    openshell_gateway_id="gateway",
    openshell_gateway_service_account="gateway",
    openshell_runner_service_account="openshell-runner",
    openshell_storage_mode="persistentVolumeClaim",
)


class PreviewIdentity(Omnigent):
    async def get(self, path, headers=None, params=None):
        cookies = SimpleCookie()
        cookies.load((headers or {}).get("cookie", ""))
        selected = cookies.get("sandbox_preview_user")
        user = (
            selected.value
            if selected and selected.value in {"alice", "bob"}
            else "alice"
        )
        return await super().get(
            path,
            headers={**(headers or {}), "cookie": f"session={user}"},
            params=params,
        )


kube, upstream = PreviewKubernetes(), PreviewIdentity()
store = Store(
    settings,
    custom=kube,
    core=kube,
    namespaces=UserNamespaces(settings, kube, kube, kube),
    metadata=kube.metadata,
)


class PreviewOpenShell(Native):
    """Simulate status revision changes and delayed policy activation."""

    def GetSandbox(self, request, **kwargs):
        key = (request.workspace_scope.workspace, request.name)
        if key in self.sandboxes:
            self.sandboxes[key].metadata.resource_version += 1
        return super().GetSandbox(request, **kwargs)

    def UpdateConfig(self, request, **kwargs):
        self.auto_load = False
        result = super().UpdateConfig(request, **kwargs)
        key = (request.workspace_scope.workspace, request.sandbox)
        revision = self.policies[key]

        def activate():
            if self.policies.get(key) is revision:
                self.load_policy(key)

        timer = threading.Timer(8, activate)
        timer.daemon = True
        timer.start()
        return result


store.integrations.items["openShell"].gateway = Gateway(
    settings.openshell_endpoint, stub=PreviewOpenShell(kube)
)
store.integrations.items["openShell"].runtime_overhead = lambda runtime: {}
store.integrations.status_sources[0].handler = lambda name: "kata-qemu-runtime-rs"
resolve_execution = store.integrations.execution


def preview_execution(resource, *, admin=False):
    target = resolve_execution(resource, admin=admin)

    class Stub:
        def ExecSandboxInteractive(self, messages):
            return EchoStream(messages)

    def connector(command, *, tty, stdin, timeout):
        return Execution(Stub(), pb.ExecSandboxRequest(command=command, tty=tty), stdin)

    return replace(target, connector=connector)


store.integrations.execution = preview_execution
cr = store.create(OWNER, "Frontend micro VM").reference
name = cr["metadata"]["name"]
if os.environ.get("PORTAL_PREVIEW_DRIFT") == "1":
    kube.items[(cr["metadata"]["namespace"], name)]["spec"]["podTemplate"]["spec"][
        "containers"
    ][0]["image"] = "example.invalid/tools:changed-outside-portal"
kube.items[(cr["metadata"]["namespace"], name)]["status"] = {
    "conditions": [
        {
            "type": "Ready",
            "status": "True",
            "observedGeneration": 1,
            "message": "micro VM ready. Your files persist across suspend and resume.",
        }
    ]
}
second = store.create(
    OWNER,
    "Research micro VM",
    size=Allocation(
        cpu_request_millicores=250,
        cpu_limit_millicores=1000,
        memory_request_mib=512,
        memory_limit_mib=2048,
        workspace_gib=10,
    ),
).reference
store.mode(second["metadata"]["name"], OWNER, "Suspended")
failed = store.create(OWNER, "Build micro VM").reference
for title in ("Team API micro VM", "Team tests micro VM"):
    team = store.create(OWNER, title, namespace_strategy="perUser")
store.sharing(team.name, OWNER, {"bob@example.com": "shell"})
store.create("bob@example.com", "Bob's team micro VM", namespace=team.scope)
other = store.create("bob@example.com", "Backend micro VM").reference
other["status"] = {
    "conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]
}
kube.items[(other["metadata"]["namespace"], other["metadata"]["name"])] = other
store.admin_control(
    name,
    cr["metadata"]["namespace"],
    cr["metadata"]["uid"],
    SandboxUpdate(
        resource_version=store.get(name, OWNER).resource_version,
        notice={
            "title": "micro VM update",
            "body": "Your micro VM is ready for the pilot.\n\nPlease suspend it when you finish for the day.\nContact platform if you need help.",
        },
    ),
    OWNER,
).reference
store.controls.save(
    GlobalUpdate(
        resource_version=store.controls.read()[1],
        creation_disabled=False,
        sandboxes_disabled=False,
        announcement={
            "title": "Pilot service notice",
            "body": "Agent Sandbox is available for experimentation.\n\nPlanned maintenance: Friday evening. Please save your work before the window.",
        },
    ),
    OWNER,
)
protected_cr = store.create(
    OWNER, "Integration examples", profile_id="protected-engineering"
).reference
pending = store.create(OWNER, "Action needs attention")
backend = store.integrations.items["agentSandbox"]
record = store.metadata.begin_operation(
    pending.record.id,
    PendingOperation(kind="mode", request_id=uuid4(), actor=OWNER),
    expected_revision=pending.record.revision,
    manifest=backend.plan_mode(pending.record.manifest, "Suspended"),
    requested_mode="suspended",
    resource_usage=pending.record.resource_usage,
)
store.metadata.operation_needs_attention(
    record.id,
    expected_revision=record.revision,
    error="The runtime did not confirm suspension. Retry the action to check whether the micro VM stopped.",
)

protected_backend = store.integrations.items["openShell"]
protected_create = protected_backend.create


def blocked_creation(*args, **kwargs):
    raise CreationRejected(
        409,
        "OpenShell cannot use the selected runtime because it has not been approved by the platform. "
        "Ask an administrator to sync the runtime configuration, then cancel this creation and create a new micro VM.\n\n"
        "OpenShell FAILED_PRECONDITION: RuntimeClass requires the approval label "
        "openshell.ai/sandbox-attachable=true.",
    )


protected_backend.create = blocked_creation
try:
    store.create(OWNER, "OpenShell setup blocked", profile_id="protected-engineering")
except HTTPException:
    pass
finally:
    protected_backend.create = protected_create

observed_status = store.status_view


def preview_status(sandbox):
    row = observed_status(sandbox)
    if sandbox.provider == "openShell":
        row["integrations"].extend(
            [
                IntegrationStatus(
                    id="envoy",
                    title="Envoy",
                    layer="Network",
                    icon="network",
                    state="configured",
                    detail="Mock example; no gateway health probe connected",
                ).model_dump(exclude_none=True),
            ]
        )
    return row


store.status_view = preview_status
for shared in (protected_cr, cr):
    value = shared if isinstance(shared, dict) else shared.reference
    store.sharing(value["metadata"]["name"], OWNER, {"bob@example.com": "view"})

sample = store.get(protected_cr["metadata"]["name"], OWNER)
network = store.integration_panel(sample, "kubernetes")
network["policy"]["spec"]["egress"] = [
    {
        "to": [
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": "team-services"}
                },
                "podSelector": {"matchLabels": {"app": "team-api"}},
            }
        ],
        "ports": [{"protocol": "TCP", "port": 8443}],
    }
]
store.update_integration(
    sample,
    "kubernetes",
    IntegrationUpdate(
        uid=network["uid"],
        revision=network["revision"],
        native_revision=network["native_revision"],
        configuration={"policy": network["policy"]},
    ),
    OWNER,
    admin=True,
)

app = create_app(settings, store, upstream, PreviewWorkspace())


@app.get("/")
def preview_home():
    return RedirectResponse(settings.base_path + "/")


@app.get("/preview")
def preview_login(user: str = "alice"):
    if user not in {"alice", "bob"}:
        raise HTTPException(422, "Choose alice or bob")
    response = RedirectResponse(
        settings.base_path + "/" + ("?owner=" + OWNER if user == "bob" else "")
    )
    response.set_cookie(
        "sandbox_preview_user",
        user,
        path=settings.base_path,
        httponly=True,
        samesite="strict",
    )
    return response
