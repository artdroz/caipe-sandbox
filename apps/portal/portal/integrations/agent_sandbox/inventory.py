"""Native manifest rendering, compute observations and namespace housekeeping."""

import hashlib
import json
import re
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime

from fastapi import HTTPException
from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.utils.quantity import parse_quantity

from ...config import runner_pull_secrets
from ...controls import SandboxControl
from ...inventory import Sandbox
from ...names import sandbox_name
from ...resources import allocation

GROUP, VERSION, PLURAL = "agents.x-k8s.io", "v1beta1", "sandboxes"
PREFIX = "sandbox.caipe.io/"
APP = "agent-sandbox-portal"
LABEL = "app.kubernetes.io/name"


def owner_key(owner):
    return hashlib.sha256(owner.encode()).hexdigest()[:32]


def owner_label(owner):
    readable = re.sub(r"[^a-z0-9.-]+", "-", owner.lower()).strip("-.")[:48].rstrip("-.")
    return f"{readable or 'user'}-{owner_key(owner)[:10]}"


def resolve(
    settings,
    owner,
    title="My sandbox",
    request_id=None,
    size=None,
    profile=None,
    namespace=None,
    catalog=None,
    namespace_strategy=None,
    namespace_owner=None,
    namespace_uid=None,
):
    from ...namespaces import namespace_config, namespace_name
    from ...profiles import MAX_SNAPSHOT_BYTES, Profiles, encoded

    catalog = catalog or Profiles(settings)
    profile = profile or catalog.get()
    size = catalog.size(profile, size)
    from .. import profile_backend

    provider = profile_backend(profile)
    request_id = uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
    name = (provider.sandbox_name if provider else sandbox_name)(request_id)
    placement = namespace_config(settings).select(namespace_strategy)
    strategy = placement.strategy
    namespace = namespace or (provider.namespace_name if provider else namespace_name)(
        settings, owner, name if strategy == "perSandbox" else None
    )
    labels = {
        LABEL: APP,
        PREFIX + "owner": owner_key(owner),
        PREFIX + "owner-email": owner_label(owner),
    }
    try:
        spec = catalog.render(profile, size)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if provider is None:
        pod = spec["podTemplate"]
        pod.setdefault("metadata", {}).setdefault("labels", {}).update(labels)
        pod["spec"]["imagePullSecrets"] = runner_pull_secrets(settings)
    snapshot = {
        "schemaVersion": 1,
        "id": profile.id,
        "revision": profile.revision,
        "definition": profile.model_dump(exclude_none=True),
        "namespace": namespace,
        "namespaceStrategy": strategy,
        "namespaceOwner": namespace_owner or owner,
        "namespaceConfiguration": placement.model_dump(exclude_none=True),
        "resources": size.model_dump(),
        "spec": deepcopy(spec),
    }
    serialized = encoded(snapshot)
    if len(serialized.encode()) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(
            422, "Resolved profile exceeds the 128 KiB allocation snapshot limit"
        )
    return {
        "apiVersion": GROUP + "/" + VERSION,
        "kind": "Sandbox",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {**labels, PREFIX + "profile": profile.id},
            "annotations": {
                PREFIX + "owner": owner,
                PREFIX + "request-id": str(request_id),
                PREFIX + "backend": provider.key if provider else "agentSandbox",
                PREFIX + "namespace-strategy": strategy,
                **(
                    {PREFIX + "namespace-owner": namespace_owner}
                    if namespace_owner
                    else {}
                ),
                **({PREFIX + "namespace-uid": namespace_uid} if namespace_uid else {}),
            },
        },
        "spec": spec,
    }, snapshot


def manifest(*args, **kwargs):
    return resolve(*args, **kwargs)[0]


def owned(cr, owner):
    metadata = cr.get("metadata", {})
    if (
        metadata.get("labels", {}).get(LABEL) != APP
        or metadata.get("annotations", {}).get(PREFIX + "owner") != owner
    ):
        raise HTTPException(404, "Sandbox not found")
    return cr


def describe(cr, provider, generic=False):
    metadata = cr["metadata"]
    annotations = metadata.get("annotations", {})
    conditions = cr.get("status", {}).get("conditions", [])
    ready = next((c for c in conditions if c.get("type") == "Ready"), {})
    mode = cr["spec"].get("operatingMode", "Running")
    if metadata.get("deletionTimestamp"):
        state = "Deleting"
    elif mode == "Suspended":
        suspended = next((c for c in conditions if c.get("type") == "Suspended"), {})
        state = (
            "Suspended"
            if suspended.get("status") == "True"
            and suspended.get("observedGeneration", 0) >= metadata.get("generation", 1)
            else "Suspending"
        )
    elif ready.get("status") == "True" and ready.get(
        "observedGeneration", 0
    ) >= metadata.get("generation", 1):
        state = "Running"
    else:
        state = "Provisioning"
    try:
        size = allocation(cr).model_dump()
    except (KeyError, StopIteration, ValueError, TypeError):
        if not generic:
            raise
        size = None
    return Sandbox(
        provider=provider,
        name=metadata["name"],
        scope=metadata["namespace"],
        uid=metadata.get("uid"),
        resource_version=metadata.get("resourceVersion"),
        owner=annotations.get(PREFIX + "owner"),
        title=annotations.get(
            PREFIX + "title", metadata["name"] if generic else "My sandbox"
        ),
        created_at=metadata.get("creationTimestamp"),
        state=state,
        message={
            "Suspending": "Stopping processes and preserving your files",
            "Suspended": "Disk retained. Resume to reconnect your tools",
            "Deleting": "Deleting sandbox resources",
        }.get(state, ready.get("message", "Waiting for sandbox readiness")),
        requested_mode=mode,
        deleting=bool(metadata.get("deletionTimestamp")),
        allocation=size,
        profile_snapshot=None,
        grants={},
        control=SandboxControl(),
        reference=cr,
    )


class Inventory:
    def verify_creation_absent(self, namespace, name, claims):
        """Refuse cancellation while target resources or retained disks remain."""
        try:
            self.custom.get_namespaced_custom_object(
                GROUP, VERSION, namespace, PLURAL, name, _request_timeout=15
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
        else:
            raise HTTPException(
                409,
                "Creation still has a Sandbox resource; retry cancellation after runtime cleanup",
            )
        for result, names in (
            (self.core.list_namespaced_pod(namespace, _request_timeout=15), {name}),
            (
                self.core.list_namespaced_persistent_volume_claim(
                    namespace, _request_timeout=15
                ),
                set(claims),
            ),
        ):
            for item in result.items:
                meta = self.namespaces.data(item).get("metadata", {})
                if meta.get("name") in names or any(
                    ref.get("kind") == "Sandbox" and ref.get("name") == name
                    for ref in meta.get("ownerReferences", [])
                ):
                    raise HTTPException(
                        409,
                        "Creation still has runtime resources or a disk; an administrator must check cleanup before cancellation",
                    )

    def __init__(self, store, custom=None, core=None, namespaces=None):
        from ...namespaces import UserNamespaces

        self.store = store
        self.settings = store.settings
        if custom is None:
            config.load_incluster_config()
        self.custom = custom or client.CustomObjectsApi()
        self.core = core or client.CoreV1Api()
        self.namespaces = namespaces or UserNamespaces(self.settings, self.core)

    def admin_get(self, name, namespace):
        try:
            return self.custom.get_namespaced_custom_object(
                GROUP, VERSION, namespace, PLURAL, name
            )
        except ApiException as exc:
            if exc.status == 404:
                raise HTTPException(404, "Sandbox not found") from None
            raise

    def retained_usage(self, owner, uids):
        usage = {"persistentvolumeclaims": 0, "requests.storage": 0}
        owned_namespaces = set(self.namespaces.for_owner(owner))
        previous = {}
        after = None
        while True:
            records = self.store.metadata.list_sandboxes(
                owner=owner, include_deleted=True, after=after, limit=200
            )
            for record in records:
                if record.binding:
                    previous.setdefault(record.scope, set()).add(record.binding.key)
            if len(records) < 200:
                break
            after = records[-1].id
        for namespace in owned_namespaces | previous.keys():
            try:
                self.core.read_namespace(namespace)
            except ApiException as exc:
                if exc.status == 404:
                    continue
                raise
            for pvc in self.core.list_namespaced_persistent_volume_claim(
                namespace
            ).items:
                references = {ref.uid for ref in pvc.metadata.owner_references or []}
                if namespace not in owned_namespaces and not references.intersection(
                    previous[namespace]
                ):
                    continue
                if not any(
                    ref.uid in uids for ref in pvc.metadata.owner_references or []
                ):
                    usage["persistentvolumeclaims"] += 1
                    usage["requests.storage"] += parse_quantity(
                        pvc.spec.resources.requests["storage"]
                    )
        return usage

    def cleanup_namespaces(self):
        if not json.loads(self.settings.namespace_policy).get("deleteWhenEmpty"):
            return
        for namespace in self.namespaces.for_owner():
            ns = self.namespaces.data(self.core.read_namespace(namespace))
            owner = ns["metadata"].get("annotations", {}).get(PREFIX + "owner")
            if not owner or self.namespaces.get(owner, namespace) != namespace:
                continue
            created = ns["metadata"].get("creationTimestamp")
            if (
                not created
                or (datetime.now(UTC) - datetime.fromisoformat(created)).total_seconds()
                < 60
            ):
                continue
            backend = self.backend_for(ns)
            with self.store.scope_operation(
                backend, namespace, required=False
            ) as guard:
                if guard is None:
                    continue
                if self.store.metadata.scope_has_sandboxes(
                    backend.key, backend.provider_instance, namespace
                ):
                    continue
                guard.check()
                if self.custom.list_namespaced_custom_object(
                    GROUP, VERSION, namespace, PLURAL
                )["items"]:
                    continue
                if (
                    self.core.list_namespaced_persistent_volume_claim(namespace).items
                    or self.core.list_namespaced_pod(namespace).items
                ):
                    continue
                pull_secrets = {
                    item["name"] for item in runner_pull_secrets(self.settings)
                }
                if any(
                    secret.metadata.name not in pull_secrets
                    or secret.type
                    not in {"kubernetes.io/dockerconfigjson", "kubernetes.io/dockercfg"}
                    for secret in self.core.list_namespaced_secret(namespace).items
                ):
                    continue
                guard.check()
                self.store.namespace_access.forget(
                    backend.key, backend.provider_instance, namespace
                )
                self.store.metadata.clear_scope_grants(
                    backend.key, backend.provider_instance, namespace
                )
                backend.cleanup_namespace(namespace)
                guard.check()
                self.core.delete_namespace(
                    namespace,
                    body={
                        "preconditions": {
                            "uid": ns["metadata"]["uid"],
                            "resourceVersion": ns["metadata"]["resourceVersion"],
                        }
                    },
                )

    def prepare(
        self,
        owner,
        title,
        request_id,
        size,
        profile,
        backend,
        *,
        namespace_strategy=None,
        namespace=None,
        namespace_owner=None,
        namespace_uid=None,
    ):
        body, snapshot = resolve(
            self.settings,
            owner,
            title,
            request_id,
            size,
            profile,
            catalog=self.store.profiles,
            namespace_strategy=namespace_strategy,
            namespace=namespace,
            namespace_owner=namespace_owner,
            namespace_uid=namespace_uid,
        )
        return replace(
            backend.describe(body),
            profile_snapshot=snapshot,
            allocation=size.model_dump(),
            title=title,
        )

    def ensure(self, cr):
        meta = cr["metadata"]
        namespace = self.namespaces.ensure(
            meta["annotations"].get(
                PREFIX + "namespace-owner", meta["annotations"][PREFIX + "owner"]
            ),
            meta["name"],
            backend=meta["annotations"][PREFIX + "backend"],
            namespace=meta["namespace"],
            strategy=meta["annotations"].get(PREFIX + "namespace-strategy"),
            expected_uid=meta["annotations"].get(PREFIX + "namespace-uid"),
        )
        if namespace != meta["namespace"]:
            raise HTTPException(409, "Resolved namespace changed during creation")

    def namespace_info(self, owner, name, backend):
        if self.namespaces.get(owner, name) != name:
            return None
        value = self.namespaces.data(self.core.read_namespace(name))
        if self.backend_for(value) is not backend:
            return None
        return {"uid": value["metadata"]["uid"]}

    def configuration(self, cr, result):
        snapshot = result.get("creation")
        result["profile_spec"] = (
            snapshot["definition"]["agentSandbox"]["spec"] if snapshot else None
        )
        if cr is None:
            return {**result, "observation_error": "Native allocation is unavailable"}
        result["native_configuration"] = {
            "apiVersion": cr["apiVersion"],
            "kind": cr["kind"],
            "metadata": {
                key: cr["metadata"].get(key, {}) for key in ("labels", "annotations")
            },
            "spec": cr["spec"],
        }
        return {
            "profile_spec": snapshot["definition"]["agentSandbox"]["spec"]
            if snapshot
            else None,
            **result,
            "namespace_configuration": self.namespaces.data(
                self.core.read_namespace(cr["metadata"]["namespace"])
            ),
            "desired": result["desired"],
            "observed": cr.get("status", {}),
        }

    def backend_for(self, resource):
        from .. import registered

        meta = resource.get("metadata", {})
        declared = meta.get("annotations", {}).get("sandbox.caipe.io/backend")
        labelled = meta.get("labels", {}).get("sandbox.caipe.io/backend")
        if declared and labelled and declared != labelled:
            raise HTTPException(
                409, "Sandbox backend identity conflicts; execution is blocked"
            )
        declared = declared or labelled
        matches = [p for p in registered() if p.managed(resource)]
        if len(matches) > 1 or (matches and declared not in (None, matches[0].key)):
            raise HTTPException(
                409, "Sandbox backend identity conflicts; execution is blocked"
            )
        if matches:
            return self.store.integrations.items[matches[0].key]
        if declared in self.store.integrations.items:
            return self.store.integrations.items[declared]
        if declared not in (None, "agentSandbox"):
            raise HTTPException(
                409, "Sandbox backend is unavailable; execution is blocked"
            )
        return self.store.integrations.items["agentSandbox"]
