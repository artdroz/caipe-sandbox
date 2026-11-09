"""Size and attach portal-owned workspace PVCs through the native driver API."""

from copy import deepcopy
from dataclasses import replace
from pathlib import PurePosixPath

from fastapi import HTTPException
from kubernetes.client import ApiException
from kubernetes.utils.quantity import parse_quantity

PREFIX = "sandbox.caipe.io/"
MODE = PREFIX + "workspace-storage"
SIZE = PREFIX + "workspace-gib"
CLASS = PREFIX + "workspace-storage-class"
UID = PREFIX + "workspace-pvc-uid"


def enabled(settings):
    return settings.openshell_storage_mode == "persistentVolumeClaim"


def managed(resource):
    return (
        resource["metadata"].get("annotations", {}).get(MODE) == "persistentVolumeClaim"
    )


def claim_name(resource):
    return "portal-workspace-" + resource["metadata"]["name"]


def home_path(spec):
    home = spec.get("environment", {}).get("HOME")
    template_home = spec.get("template", {}).get("environment", {}).get("HOME")
    if (
        not isinstance(home, str)
        or not home.startswith("/sandbox/")
        or ".." in PurePosixPath(home).parts
        or str(PurePosixPath(home)) != home
        or not home.isprintable()
        or (template_home is not None and template_home != home)
    ):
        raise ValueError(
            "OpenShell persistentVolumeClaim storage requires environment.HOME below /sandbox, such as /sandbox/home"
        )
    return home


def prepare(draft, settings):
    if not enabled(settings):
        return draft
    from ...resources import Allocation
    from ...profiles import MAX_SNAPSHOT_BYTES, encoded

    size = Allocation.model_validate(draft.allocation)
    body = deepcopy(draft.reference)
    body["metadata"]["annotations"].update(
        {
            MODE: "persistentVolumeClaim",
            SIZE: str(size.workspace_gib),
            CLASS: settings.storage_class,
        }
    )
    body["spec"]["template"]["driver_config"] = {
        "kubernetes": {
            "volumes": [
                {
                    "name": "portal-workspace",
                    "persistent_volume_claim": {
                        "claim_name": claim_name(body),
                        "read_only": False,
                    },
                }
            ],
            "containers": {
                "agent": {
                    "volume_mounts": [
                        {
                            "name": "portal-workspace",
                            "mount_path": home_path(body["spec"]),
                            "read_only": False,
                        }
                    ]
                }
            },
        }
    }
    snapshot = deepcopy(draft.profile_snapshot)
    snapshot["spec"] = deepcopy(body["spec"])
    if len(encoded(snapshot).encode()) > MAX_SNAPSHOT_BYTES:
        raise HTTPException(
            422, "Resolved profile exceeds the 128 KiB allocation snapshot limit"
        )
    return replace(draft, reference=body, profile_snapshot=snapshot)


class WorkspaceVolumes:
    def __init__(self, integration):
        self.integration = integration
        self.catalog = integration.catalog
        self.core = self.catalog.core

    def read(self, resource, *, allow_missing=False):
        meta = resource["metadata"]
        try:
            pvc = self.core.read_namespaced_persistent_volume_claim(
                claim_name(resource),
                meta.get("workspace", meta.get("namespace")),
                _request_timeout=15,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            if allow_missing:
                return None
            raise HTTPException(
                409,
                "OpenShell workspace disk is missing; an administrator must check storage",
            ) from None
        return self.catalog.namespaces.data(pvc)

    def verify(self, resource, pvc):
        meta, actual = resource["metadata"], pvc["metadata"]
        annotations = meta["annotations"]
        expected_labels = {
            PREFIX + "instance": self.integration.instance,
            PREFIX + "request-id": annotations[PREFIX + "request-id"],
            PREFIX + "owner": meta["labels"][PREFIX + "owner"],
            "openshell.ai/sandbox-attachable": "true",
            "openshell.ai/sandbox-attachable-workspace": meta.get("workspace", meta.get("namespace")),
        }
        spec = pvc["spec"]
        if (
            any(
                actual.get("labels", {}).get(k) != v for k, v in expected_labels.items()
            )
            or (resource["apiVersion"] != "openshell.v1" and not annotations.get(UID))
            or (annotations.get(UID) and annotations[UID] != actual["uid"])
            or actual.get("deletionTimestamp")
            or spec.get("accessModes") != ["ReadWriteOnce"]
            or spec.get("volumeMode", "Filesystem") != "Filesystem"
            or parse_quantity(spec["resources"]["requests"]["storage"])
            != int(annotations[SIZE]) * 1024**3
            or (
                annotations[CLASS]
                and spec.get("storageClassName") != annotations[CLASS]
            )
        ):
            raise HTTPException(
                409, "OpenShell workspace disk changed or belongs to another allocation"
            )
        return pvc

    def ensure(self, resource):
        meta = resource["metadata"]
        namespace = meta["workspace"]
        annotations = meta["annotations"]
        body = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {
                "name": claim_name(resource),
                "namespace": namespace,
                "labels": {
                    "app.kubernetes.io/name": "agent-sandbox-portal",
                    PREFIX + "instance": self.integration.instance,
                    PREFIX + "request-id": annotations[PREFIX + "request-id"],
                    PREFIX + "owner": meta["labels"][PREFIX + "owner"],
                    "openshell.ai/sandbox-attachable": "true",
                    "openshell.ai/sandbox-attachable-workspace": namespace,
                },
            },
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "volumeMode": "Filesystem",
                "resources": {"requests": {"storage": annotations[SIZE] + "Gi"}},
                **(
                    {"storageClassName": annotations[CLASS]}
                    if annotations[CLASS]
                    else {}
                ),
            },
        }
        try:
            self.core.create_namespaced_persistent_volume_claim(
                namespace, body, _request_timeout=15
            )
        except ApiException as exc:
            if exc.status == 403:
                raise HTTPException(
                    503,
                    "Portal cannot provision the workspace disk; an administrator must sync storage permissions",
                ) from None
            if exc.status != 409:
                raise
        pvc = self.verify(resource, self.read(resource))
        if pvc["metadata"].get("ownerReferences"):
            raise HTTPException(
                409,
                "Workspace disk already belongs to a Sandbox; refresh before retrying",
            )
        return pvc["metadata"]["uid"]

    def bind(self, cr):
        if not managed(cr):
            return
        pvc = self.verify(cr, self.read(cr))
        meta = cr["metadata"]
        owner = {
            "apiVersion": cr["apiVersion"],
            "kind": "Sandbox",
            "name": meta["name"],
            "uid": meta["uid"],
        }
        owners = pvc["metadata"].get("ownerReferences", [])
        if owners:
            if len(owners) != 1 or any(owners[0].get(k) != v for k, v in owner.items()):
                raise HTTPException(409, "Workspace disk owner changed")
            return
        self.core.patch_namespaced_persistent_volume_claim(
            claim_name(cr),
            meta["namespace"],
            {
                "metadata": {
                    "uid": pvc["metadata"]["uid"],
                    "resourceVersion": pvc["metadata"]["resourceVersion"],
                    "ownerReferences": [owner],
                }
            },
            _request_timeout=15,
        )

    def cancel(self, resource):
        if not managed(resource):
            return
        pvc = self.read(resource, allow_missing=True)
        if pvc is None:
            return
        self.verify(resource, pvc)
        if pvc["metadata"].get("ownerReferences"):
            raise HTTPException(
                409,
                "Workspace disk still belongs to a Sandbox; wait for runtime cleanup",
            )
        namespace = resource["metadata"]["workspace"]
        for item in self.core.list_namespaced_pod(namespace, _request_timeout=15).items:
            pod = self.catalog.namespaces.data(item)
            if any(
                volume.get("persistentVolumeClaim", {}).get("claimName")
                == claim_name(resource)
                for volume in pod.get("spec", {}).get("volumes", [])
            ):
                raise HTTPException(
                    409, "Workspace disk is still mounted; wait for runtime cleanup"
                )
        self.core.delete_namespaced_persistent_volume_claim(
            claim_name(resource),
            namespace,
            body={
                "preconditions": {
                    "uid": pvc["metadata"]["uid"],
                    "resourceVersion": pvc["metadata"]["resourceVersion"],
                }
            },
            _request_timeout=15,
        )
