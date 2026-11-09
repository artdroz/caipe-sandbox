"""Native SandboxSpec validation and portal resource choices."""

import json
from copy import deepcopy
from decimal import DecimalException

from google.protobuf.json_format import ParseDict
from kubernetes.utils.quantity import parse_quantity
from openshell._proto import openshell_pb2 as pb
from pydantic import BaseModel, ConfigDict

from ...config import runtime_classes
from ...resources import Allocation, chosen, policy
from .volumes import enabled, home_path


class OpenShell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: dict


def validate_settings(settings):
    from .client import gateway_address
    from .service import namespace_name

    if settings.openshell_storage_mode not in {"gateway", "persistentVolumeClaim"}:
        raise ValueError(
            "OpenShell storageMode must be gateway or persistentVolumeClaim"
        )

    if not all(
        (
            settings.openshell_endpoint,
            settings.openshell_gateway_id,
            settings.openshell_gateway_service_account,
            settings.openshell_runner_service_account,
        )
    ):
        raise ValueError(
            "OpenShell profiles require deployment-owned gateway connection and service accounts"
        )
    supervisor_resources(settings)
    namespace_name(settings, "validation")
    gateway_address(settings.openshell_endpoint)


def resource_bounds(settings):
    if enabled(settings):
        return {}
    return {
        "workspace_gib": {
            "min": settings.openshell_storage_gib,
            "max": settings.openshell_storage_gib,
        }
    }


def validate_size(allocation, settings):
    if (
        not enabled(settings)
        and allocation.workspace_gib != settings.openshell_storage_gib
    ):
        raise ValueError("OpenShell disk size is fixed by the gateway configuration")


def capabilities(settings=None):
    return {
        "resize": False,
        "storage_source": "profile" if settings and enabled(settings) else "platform",
    }


def validate_spec(spec):
    try:
        value = ParseDict(spec, pb.SandboxSpec())
    except Exception as exc:
        raise ValueError(
            "openShell.spec must match the native OpenShell SandboxSpec"
        ) from exc
    if not value.template.image or not value.command:
        raise ValueError("OpenShell profiles require an image and startup command")
    if value.policy.version != 1:
        raise ValueError("The supported OpenShell policy version is 1")
    if value.template.driver_config.fields:
        raise ValueError(
            "Caller driver_config is unavailable in the initial OpenShell integration"
        )
    return value


def size(profile, settings):
    defaults = policy(settings).defaults
    resources = profile.openShell.spec.get("template", {}).get("resources", {})
    values = defaults.model_dump()
    for kind in ("request", "limit"):
        section = resources.get(kind + "s", {})
        if "cpu" in section:
            values[f"cpu_{kind}_millicores"] = int(
                parse_quantity(section["cpu"]) * 1000
            )
        if "memory" in section:
            values[f"memory_{kind}_mib"] = int(
                parse_quantity(section["memory"]) / 1024**2
            )
    values["workspace_gib"] = settings.openshell_storage_gib
    return chosen(settings, Allocation(**values))


def render(profile, allocation, settings):
    validate_size(allocation, settings)
    spec = deepcopy(profile.openShell.spec)
    template = spec.setdefault("template", {})
    runtime = template.setdefault("runtime_class_name", settings.runtime_class)
    if runtime not in runtime_classes(settings):
        raise ValueError("OpenShell requires a deployment-approved runtime class")
    template["resources"] = allocation.container_resources()
    validate_spec(spec)
    if enabled(settings):
        home_path(spec)
    return spec


def supervisor_resources(settings):
    resources = json.loads(settings.openshell_supervisor_resources)
    try:
        if set(resources) != {"requests", "limits"}:
            raise ValueError
        for kind in ("requests", "limits"):
            if set(resources[kind]) != {"cpu", "memory"}:
                raise ValueError
        for resource in ("cpu", "memory"):
            request, limit = (
                parse_quantity(resources[kind][resource])
                for kind in ("requests", "limits")
            )
            if (
                not request.is_finite()
                or not limit.is_finite()
                or not 0 < request <= limit
            ):
                raise ValueError
    except (KeyError, TypeError, ValueError, DecimalException):
        raise ValueError(
            "OpenShell supervisorResources requires positive CPU/memory requests and limits with requests <= limits"
        ) from None
    return resources
