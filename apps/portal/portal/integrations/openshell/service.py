"""OpenShell gateway lifecycle, identity verification and native observations."""

import hashlib
import threading
from copy import deepcopy
from dataclasses import replace

from fastapi import HTTPException
from google.protobuf.json_format import ParseDict
from openshell._proto import openshell_pb2 as pb
from openshell._proto import sandbox_pb2 as spb

from ...storage import NativeBinding
from ..agent_sandbox.inventory import Inventory, describe
from ..agent_sandbox.metadata import (
    binding as compute_binding,
)
from ..agent_sandbox.metadata import (
    contains,
    manifest,
    native_errors,
)
from ..agent_sandbox.status import enrich
from ..status import IntegrationStatus
from . import policy
from .client import Gateway, data, scope

PREFIX = "sandbox.caipe.io/"
NATIVE = "openshell.ai/"
GROUP, VERSION, PLURAL = "agents.x-k8s.io", "v1beta1", "sandboxes"
LIFECYCLE_TIMEOUT = 90


def integration_badge(row, state, detail):
    row.setdefault("integrations", []).append(
        IntegrationStatus(
            id=policy.descriptor["id"],
            title=policy.descriptor["title"],
            layer="Runtime",
            icon=policy.descriptor["icon"],
            state=state,
            detail=detail,
        ).model_dump(exclude_none=True)
    )
    return row


def admitted(sandbox, config):
    status = sandbox.status
    admission = status.configuration_admission
    return (
        status.phase == pb.SANDBOX_PHASE_READY
        and admission.state == pb.CONFIGURATION_ADMISSION_STATE_ACCEPTED
        and config.configuration_admitted
        and bool(config.policy_hash)
        and bool(config.configuration_instance_id)
        and status.current_policy_version == admission.policy_version == config.version
        and admission.policy_hash == config.policy_hash
        and admission.instance_id == config.configuration_instance_id
        and admission.config_revision == config.config_revision
        and admission.provider_env_revision == config.provider_env_revision
    )


def namespace_name(settings, owner, sandbox=None):
    prefix = settings.namespace_prefix + "-o-"
    if len(prefix) > 9:
        raise ValueError(
            "OpenShell workspace names require namespacePrefix of at most six characters"
        )
    value = settings.namespace_access_role + "/" + owner + "/" + (sandbox or "")
    return prefix + hashlib.sha256(value.encode()).hexdigest()[: 19 - len(prefix)]


class Integration:
    namespace_network_selector = {
        "matchLabels": {"openshell.ai/component": "supervisor"}
    }
    key = "openShell"

    def __init__(self, store, gateway=None, *, catalog=None):
        self.store = store
        self.catalog = catalog or Inventory(store)
        self.settings = store.settings
        self.gateway = gateway
        self.connection_lock = threading.Lock()
        self.instance = hashlib.sha256(
            self.settings.namespace_access_role.encode()
        ).hexdigest()[:32]
        self.provider_instance = f"{self.settings.openshell_gateway_id}/{self.instance}"

    @staticmethod
    def binding(cr):
        saved = compute_binding(cr)
        labels = cr["metadata"]["labels"]
        return NativeBinding(
            key=saved.key,
            reference={
                **saved.reference,
                "gateway_id": labels[NATIVE + "gateway-id"],
                "sandbox_id": labels[NATIVE + "sandbox-id"],
            },
        )

    def manifest(self, reference):
        if reference["apiVersion"] == "openshell.v1":
            return deepcopy(reference)
        value = manifest(reference)
        meta = value["metadata"]
        meta["workspace"] = meta.pop("namespace")
        value["apiVersion"] = "openshell.v1"
        return value

    @native_errors
    def observe(self, saved):
        ref = saved.reference
        cr = self.catalog.custom.get_namespaced_custom_object(
            GROUP, VERSION, ref["namespace"], PLURAL, ref["name"], _request_timeout=15
        )
        if self.binding(cr) != saved:
            raise HTTPException(409, "OpenShell allocation identity changed")
        self.native(cr)
        return self.describe(cr)

    @native_errors
    def find_created(self, manifest, request_id):
        meta = manifest["metadata"]
        try:
            sandbox = self.client.get(meta["workspace"], meta["name"])
        except HTTPException as exc:
            if exc.status_code == 404:
                return None
            raise
        if (
            sandbox.metadata.annotations.get(PREFIX + "request-id") != str(request_id)
            or sandbox.metadata.annotations.get(PREFIX + "owner")
            != meta["annotations"][PREFIX + "owner"]
            or sandbox.metadata.labels.get(PREFIX + "instance") != self.instance
        ):
            raise HTTPException(
                409, "Creation request conflicts with an existing OpenShell allocation"
            )
        return self.record(sandbox)

    @native_errors
    def verify_creation_absent(self, manifest, *, rejected):
        if not rejected:
            raise HTTPException(
                409,
                "The original creation outcome is still unknown. An administrator "
                "must verify that OpenShell has finished the request and cleaned up "
                "its resources before this creation can be cancelled.",
            )
        meta = manifest["metadata"]
        self.catalog.verify_creation_absent(
            meta["workspace"], meta["name"], ["workspace-" + meta["name"]]
        )

    @property
    def client(self):
        if not self.settings.openshell_endpoint:
            raise HTTPException(503, "OpenShell gateway is not configured")
        with self.connection_lock:
            if self.gateway is None:
                self.gateway = Gateway(self.settings.openshell_endpoint)
        return self.gateway

    def close(self):
        if self.gateway:
            self.gateway.close()

    def native(self, cr):
        meta = cr["metadata"]
        labels = meta.get("labels", {})
        if labels.get(NATIVE + "gateway-id") != self.settings.openshell_gateway_id:
            raise HTTPException(
                409, "This OpenShell allocation belongs to another gateway"
            )
        sandbox = self.client.get(meta["namespace"], meta["name"])
        self.verify(cr, sandbox)
        return sandbox

    def verify(self, cr, sandbox):
        meta = cr["metadata"]
        identity = sandbox.metadata.annotations.get(
            "internal.openshell.ai/compute-runtime-identity", ""
        )
        if (
            meta.get("labels", {}).get(NATIVE + "gateway-id")
            != self.settings.openshell_gateway_id
            or sandbox.metadata.id != meta.get("labels", {}).get(NATIVE + "sandbox-id")
            or sandbox.metadata.workspace != meta["namespace"]
            or not identity.startswith(
                f"kubernetes://{meta['namespace']}/{meta['uid']}/"
            )
        ):
            raise HTTPException(
                409, "OpenShell allocation identity changed; refresh before retrying"
            )

    def record(self, sandbox):
        meta = sandbox.metadata
        cr = self.catalog.custom.get_namespaced_custom_object(
            GROUP, VERSION, meta.workspace, PLURAL, meta.name
        )
        self.verify(cr, sandbox)
        owner = meta.annotations.get(PREFIX + "owner")
        annotations = {
            k: v for k, v in meta.annotations.items() if k.startswith(PREFIX)
        }
        labels = {
            k: v
            for k, v in meta.labels.items()
            if k.startswith(PREFIX) or k == "app.kubernetes.io/name"
        }
        if (
            not owner
            or labels.get(PREFIX + "instance") != self.instance
            or labels.get(PREFIX + "owner")
            != hashlib.sha256(owner.encode()).hexdigest()[:32]
        ):
            raise HTTPException(
                409, "OpenShell allocation has no matching portal ownership"
            )
        namespace_owner = annotations.get(PREFIX + "namespace-owner", owner)
        if (
            self.catalog.namespaces.get(namespace_owner, meta.workspace)
            != meta.workspace
        ):
            raise HTTPException(
                409, "OpenShell namespace is not owned by this portal user"
            )
        existing = cr["metadata"].get("annotations", {})
        if existing.get(PREFIX + "owner"):
            if existing[PREFIX + "owner"] != owner:
                raise HTTPException(409, "OpenShell ownership metadata conflicts")
            return cr
        return self.catalog.custom.patch_namespaced_custom_object(
            GROUP,
            VERSION,
            meta.workspace,
            PLURAL,
            meta.name,
            {
                "metadata": {
                    "resourceVersion": cr["metadata"]["resourceVersion"],
                    "annotations": annotations,
                    "labels": labels,
                }
            },
        )

    @native_errors
    def create(self, body, request_id):
        with self.store.scope_operation(self, body["metadata"]["workspace"]) as owner:
            owner.check()
            self.ensure(body)
            owner.check()
            return self._create(body, request_id)

    def _create(self, body, request_id):
        meta = body["metadata"]
        namespace = meta["workspace"]
        labels = {**meta["labels"], PREFIX + "instance": self.instance}
        workspace_owner = hashlib.sha256(
            meta["annotations"]
            .get(PREFIX + "namespace-owner", meta["annotations"][PREFIX + "owner"])
            .encode()
        ).hexdigest()[:32]
        try:
            workspace = self.client.call(
                "GetWorkspace", pb.GetWorkspaceRequest(name=namespace)
            ).workspace
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            workspace = self.client.call(
                "CreateWorkspace",
                pb.CreateWorkspaceRequest(
                    name=namespace,
                    labels={
                        PREFIX + "owner": workspace_owner,
                        PREFIX + "instance": self.instance,
                    },
                ),
            ).workspace
        if (
            workspace.metadata.labels.get(PREFIX + "owner") != workspace_owner
            or workspace.metadata.labels.get(PREFIX + "instance") != self.instance
        ):
            raise HTTPException(
                409, "OpenShell workspace belongs to another owner or portal"
            )
        sandbox = self.client.call(
            "CreateSandbox",
            pb.CreateSandboxRequest(
                name=meta["name"],
                workspace_scope=scope(namespace),
                labels=labels,
                annotations=meta["annotations"],
                spec=ParseDict(body["spec"], pb.SandboxSpec()),
            ),
        ).sandbox
        cr = self.record(sandbox)
        return cr

    @native_errors
    def mode(self, cr, mode, *, request_id=None):
        sandbox = self.native(cr)
        accepted = {
            "Running": {pb.SANDBOX_PHASE_READY, pb.SANDBOX_PHASE_STARTING},
            "Suspended": {pb.SANDBOX_PHASE_STOPPED, pb.SANDBOX_PHASE_STOPPING},
        }
        # These durable phases already confirm the requested transition.
        if sandbox.status.phase in accepted[mode]:
            return self.catalog.admin_get(
                cr["metadata"]["name"], cr["metadata"]["namespace"]
            )
        request = (
            pb.StartSandboxRequest if mode == "Running" else pb.StopSandboxRequest
        )(
            workspace_scope=scope(sandbox.metadata.workspace),
            name=sandbox.metadata.name,
        )
        result = self.client.call(
            "StartSandbox" if mode == "Running" else "StopSandbox",
            request,
            # Kubernetes shutdown can exceed the short inventory deadline.
            timeout=LIFECYCLE_TIMEOUT,
        )
        self.verify(cr, result.sandbox)
        return self.catalog.admin_get(
            cr["metadata"]["name"], cr["metadata"]["namespace"]
        )

    @native_errors
    def delete(self, cr, *, request_id=None):
        sandbox = self.native(cr)
        if sandbox.status.phase == pb.SANDBOX_PHASE_DELETING:
            return {"status": "deleting"}
        result = self.client.call(
            "DeleteSandbox",
            pb.DeleteSandboxRequest(
                workspace_scope=scope(sandbox.metadata.workspace),
                name=sandbox.metadata.name,
            ),
            timeout=LIFECYCLE_TIMEOUT,
        )
        if result.sandbox_id and result.sandbox_id != sandbox.metadata.id:
            raise HTTPException(409, "OpenShell deletion returned another allocation")
        return {"status": "deleting"}

    @native_errors
    def status(self, cr, row):
        if cr is None:
            row["capabilities"] = {"resize": False}
            return integration_badge(
                row, "unknown", "OpenShell observation is unavailable"
            )
        if cr["metadata"].get("deletionTimestamp"):
            row["state"] = "Deleting"
            return integration_badge(row, "inactive", "Sandbox is being deleted")
        try:
            sandbox = self.native(cr)
            status = sandbox.status
            phase = pb.SandboxPhase.Name(status.phase).removeprefix("SANDBOX_PHASE_")
            row["state"] = {
                "READY": "Running",
                "STOPPED": "Suspended",
                "STOPPING": "Suspending",
                "ERROR": "Error",
                "DELETING": "Deleting",
                "COMPLETED": "Error",
            }.get(phase, "Provisioning")
            active = phase == "READY" and admitted(sandbox, self.config(sandbox))
            integration_state = (
                "active"
                if active
                else "inactive"
                if phase == "STOPPED"
                else "error"
                if phase in {"ERROR", "COMPLETED"}
                else "pending"
            )
            if phase == "READY" and not active:
                row["state"] = "Provisioning"
            row["message"] = (
                "micro VM ready"
                if active
                else "Waiting for runtime policy"
                if phase != "STOPPED"
                else "Disk retained. Resume to reconnect your tools"
            )
            detail = (
                f"Policy version {status.current_policy_version} admitted"
                if active
                else row["message"]
            )
            if phase in {"READY", "ERROR"} and (
                status.configuration_admission.state
                == pb.CONFIGURATION_ADMISSION_STATE_REJECTED
            ):
                row.update(
                    state="Error",
                    message=status.configuration_admission.error
                    or "OpenShell rejected the runtime policy",
                )
                integration_state, detail = "error", row["message"]
            row["capabilities"] = {
                "resize": False,
                "suspend": phase in {"READY", "ERROR"},
            }
        except HTTPException:
            row.update(
                state="Error",
                message="OpenShell status unavailable; execution is blocked",
                capabilities={"resize": False},
            )
            integration_state, detail = "unknown", row["message"]
        integration_badge(row, integration_state, detail)
        return enrich(self.catalog.core, cr, row)

    def ready(self, cr, pod_uid=None):
        sandbox = self.native(cr)
        if not admitted(sandbox, self.config(sandbox)):
            raise HTTPException(409, "OpenShell protection is not ready")
        if pod_uid and self.workload(cr).metadata.uid != pod_uid:
            raise HTTPException(409, "OpenShell workload identity changed")
        return sandbox

    def config(self, sandbox):
        return self.client.call(
            "GetSandboxConfig",
            spb.GetSandboxConfigRequest(
                workspace_scope=scope(sandbox.metadata.workspace),
                name=sandbox.metadata.name,
            ),
        )

    @native_errors
    def workload(self, cr):
        meta = cr["metadata"]
        pod = self.catalog.core.read_namespaced_pod(
            cr.get("status", {}).get("podName") or meta["name"], meta["namespace"]
        )
        if pod.status.phase != "Running" or not any(
            ref.uid == meta["uid"] for ref in pod.metadata.owner_references or []
        ):
            raise HTTPException(409, "Sandbox terminal is not ready")
        return pod

    def execution(self, cr, *, admin=False):
        from ...execution import ExecutionTarget

        meta = cr["metadata"]
        pod = self.workload(cr)
        pod_uid = pod.metadata.uid
        self.ready(cr)

        def connector(command, *, tty, stdin, timeout):
            return self.connect(
                cr, command, pod_uid=pod_uid, tty=tty, stdin=stdin, timeout=timeout
            )

        return ExecutionTarget(
            key=("openShell", meta["namespace"], pod_uid),
            scope=meta["namespace"],
            sandbox_uid=meta["uid"],
            connector=connector,
        )

    def connect(self, cr, command, tty=True, stdin=True, pod_uid=None, timeout=20):
        sandbox = self.ready(cr, pod_uid)
        return self.client.connect(
            sandbox.metadata.workspace,
            sandbox.metadata.name,
            command,
            tty,
            stdin,
            timeout=timeout,
        )

    def cleanup_namespace(self, namespace):
        self.client.call(
            "DeleteWorkspace",
            pb.DeleteWorkspaceRequest(name=namespace, allow_missing=True),
        )

    def allocation(self, cr, *, snapshot=None):
        from kubernetes.utils.quantity import parse_quantity

        from ...resources import Allocation, allocation

        if cr["apiVersion"] != "openshell.v1":
            size = allocation(cr)
        else:
            spec = cr["spec"]["template"]["resources"]
            size = Allocation(
                cpu_request_millicores=int(
                    parse_quantity(spec["requests"]["cpu"]) * 1000
                ),
                cpu_limit_millicores=int(parse_quantity(spec["limits"]["cpu"]) * 1000),
                memory_request_mib=int(
                    parse_quantity(spec["requests"]["memory"]) / 1024**2
                ),
                memory_limit_mib=int(
                    parse_quantity(spec["limits"]["memory"]) / 1024**2
                ),
                workspace_gib=snapshot["resources"]["workspace_gib"]
                if snapshot
                else self.settings.openshell_storage_gib,
            )
        return size

    def usage(self, cr):
        from kubernetes.utils.quantity import parse_quantity

        from .profile import supervisor_resources

        size = self.allocation(cr)
        runtime = (
            cr["spec"]["template"].get("runtime_class_name")
            if cr["apiVersion"] == "openshell.v1"
            else cr["spec"]["podTemplate"]["spec"].get("runtimeClassName")
        )
        overhead = self.runtime_overhead(runtime)
        usage = {
            "requests.storage": parse_quantity(f"{size.workspace_gib}Gi"),
            "persistentvolumeclaims": 1,
            "pods": 2,
            "count/sandboxes.agents.x-k8s.io": 1,
        }
        for kind, supervisor in supervisor_resources(self.settings).items():
            resources = size.container_resources()[kind]
            for resource in ["cpu", "memory"]:
                usage[kind + "." + resource] = (
                    parse_quantity(resources[resource])
                    + parse_quantity(supervisor[resource])
                    + parse_quantity(overhead.get(resource, "0"))
                )
        return usage

    @native_errors
    def runtime_overhead(self, runtime):
        from kubernetes import client

        if not runtime:
            return {}
        with client.ApiClient() as api:
            runtime_class = client.NodeV1Api(api).read_runtime_class(
                runtime, _request_timeout=10
            )
        return (
            self.catalog.namespaces.data(runtime_class)
            .get("overhead", {})
            .get("podFixed", {})
        )

    @native_errors
    def configure(self, cr, size, *, manifest=None):
        raise HTTPException(
            409,
            "OpenShell resource changes require a supported native recreation operation",
        )

    plan_configure = configure

    def drift(self, saved, reference):
        sandbox, _, status = policy.snapshot(self, reference)
        expected = deepcopy(saved["spec"])
        saved_policy = expected.pop("policy")
        actual = data(sandbox.spec)
        actual.pop("policy", None)
        return not contains(actual, expected) or policy.different(
            saved_policy, data(status.revision.policy)
        )

    def validate_created(self, native, saved, *, snapshot=None):
        if self.allocation(native) != self.allocation(saved, snapshot=snapshot):
            raise HTTPException(
                409,
                "OpenShell allocated different resources; administrator investigation is required",
            )

    def plan_mode(self, saved, mode):
        return deepcopy(saved)

    @native_errors
    def configuration(self, cr, result):
        snapshot = result.get("creation")
        result["profile_spec"] = (
            snapshot["definition"]["openShell"]["spec"] if snapshot else None
        )
        result["capabilities"] = {"resize": False}
        if cr is None:
            return {**result, "observation_error": "Native allocation is unavailable"}
        sandbox = self.native(cr)
        config = self.config(sandbox)
        settings = data(config)
        effective_policy = settings.pop("policy", {})
        result["namespace_configuration"] = self.catalog.namespaces.data(
            self.catalog.core.read_namespace(cr["metadata"]["namespace"])
        )
        result["native_configuration"] = {
            "apiVersion": "openshell.v1",
            "kind": "Sandbox",
            "metadata": {
                "id": sandbox.metadata.id,
                "name": sandbox.metadata.name,
                "workspace": sandbox.metadata.workspace,
            },
            "spec": {**data(sandbox.spec), "policy": effective_policy},
            "configuration": settings,
            "status": data(sandbox.status),
        }
        result["observed"] = data(sandbox.status)
        snapshot = result.get("creation")
        result["profile_spec"] = (
            snapshot["definition"]["openShell"]["spec"] if snapshot else None
        )
        result["capabilities"] = {"resize": False}
        return result

    def describe(self, cr):
        return describe(cr, self.key, generic=True)

    def prepare(
        self,
        owner,
        title,
        request_id,
        size,
        profile,
        *,
        namespace_strategy=None,
        namespace=None,
        namespace_owner=None,
        namespace_uid=None,
    ):
        draft = self.catalog.prepare(
            owner,
            title,
            request_id,
            size,
            profile,
            self,
            namespace_strategy=namespace_strategy,
            namespace=namespace,
            namespace_owner=namespace_owner,
            namespace_uid=namespace_uid,
        )
        return replace(draft, reference=self.manifest(draft.reference))

    @native_errors
    def namespace_info(self, owner, name):
        return self.catalog.namespace_info(owner, name, self)

    @native_errors
    def ensure(self, reference):
        body = deepcopy(reference)
        body["metadata"]["namespace"] = body["metadata"].pop("workspace")
        return self.catalog.ensure(body)

    @native_errors
    def retained_usage(self, owner, uids):
        return {}

    def cleanup(self):
        pass
