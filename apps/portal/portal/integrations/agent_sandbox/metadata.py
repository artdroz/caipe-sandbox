"""Serializable native identities and manifests for Kubernetes-backed compute."""

from copy import deepcopy
from functools import wraps

from fastapi import HTTPException
from kubernetes.client import ApiException
from urllib3.exceptions import HTTPError

from ...storage import NativeBinding
from ..errors import CreationRejected

PREFIX = "sandbox.caipe.io/"


def binding(cr):
    meta = cr["metadata"]
    return NativeBinding(
        key=meta["uid"],
        reference={
            "name": meta["name"],
            "namespace": meta["namespace"],
            "uid": meta["uid"],
        },
    )


def verify_binding(cr, saved):
    if binding(cr) != saved:
        raise HTTPException(
            409,
            "Native sandbox identity changed; administrator investigation is required",
        )


def manifest(cr):
    meta = deepcopy(cr["metadata"])
    for key in (
        "uid",
        "resourceVersion",
        "generation",
        "creationTimestamp",
        "deletionTimestamp",
        "managedFields",
        "finalizers",
        "ownerReferences",
    ):
        meta.pop(key, None)
    annotations = meta.get("annotations", {})
    for key in ("profile", "shares", "admin-control", "title", "schema"):
        annotations.pop(PREFIX + key, None)
    return {
        "apiVersion": cr["apiVersion"],
        "kind": cr["kind"],
        "metadata": meta,
        "spec": deepcopy(cr["spec"]),
    }


def native_errors(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiException as exc:
            code = (
                404
                if exc.status == 404
                else 409
                if exc.status == 409
                else 422
                if exc.status in {400, 422}
                else 503
            )
            exception = CreationRejected if exc.status in {400, 422} else HTTPException
            raise exception(
                code,
                "Native sandbox configuration was rejected"
                if code == 422
                else "Native sandbox changed; refresh and retry"
                if code == 409
                else "Native sandbox was not found"
                if code == 404
                else "Native sandbox service is unavailable",
            ) from None
        except (HTTPError, OSError):
            raise HTTPException(503, "Native sandbox service is unavailable") from None

    return wrapped


def contains(observed, desired):
    """Compare owned fields while allowing server-defaulted dictionary fields."""
    if isinstance(desired, dict):
        return isinstance(observed, dict) and all(
            contains(observed.get(k), v) for k, v in desired.items()
        )
    if isinstance(desired, list):
        return (
            isinstance(observed, list)
            and len(observed) == len(desired)
            and all(contains(a, b) for a, b in zip(observed, desired, strict=True))
        )
    return observed == desired
