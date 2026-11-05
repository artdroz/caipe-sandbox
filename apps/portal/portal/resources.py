"""Validated per-sandbox allocations, stored in the Kubernetes spec."""

import json

from fastapi import HTTPException
from kubernetes.utils.quantity import parse_quantity
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_POLICY = {
    "defaults": {
        "cpu_request_millicores": 500,
        "cpu_limit_millicores": 2000,
        "memory_request_mib": 1024,
        "memory_limit_mib": 4096,
        "workspace_gib": 20,
    },
    "cpu_millicores": {"min": 100, "max": 4000},
    "memory_mib": {"min": 256, "max": 8192},
    "workspace_gib": {"min": 1, "max": 200},
}


class Allocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_request_millicores: int = Field(strict=True, gt=0)
    cpu_limit_millicores: int = Field(strict=True, gt=0)
    memory_request_mib: int = Field(strict=True, gt=0)
    memory_limit_mib: int = Field(strict=True, gt=0)
    workspace_gib: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def requests_fit_limits(self):
        if self.cpu_request_millicores > self.cpu_limit_millicores:
            raise ValueError("Reserved CPU must not exceed the CPU limit")
        if self.memory_request_mib > self.memory_limit_mib:
            raise ValueError("Reserved memory must not exceed the memory limit")
        return self

    def container_resources(self):
        return {
            "requests": {
                "cpu": f"{self.cpu_request_millicores}m",
                "memory": f"{self.memory_request_mib}Mi",
                "ephemeral-storage": "2Gi",
            },
            "limits": {
                "cpu": f"{self.cpu_limit_millicores}m",
                "memory": f"{self.memory_limit_mib}Mi",
                "ephemeral-storage": "8Gi",
            },
        }


class Bounds(BaseModel):
    min: int = Field(strict=True, gt=0)
    max: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.min > self.max:
            raise ValueError("Minimum resource size exceeds maximum")
        return self


class ResourcePolicy(BaseModel):
    defaults: Allocation
    cpu_millicores: Bounds
    memory_mib: Bounds
    workspace_gib: Bounds

    @model_validator(mode="after")
    def defaults_in_bounds(self):
        self.validate_allocation(self.defaults)
        return self

    def validate_allocation(self, allocation):
        for field, value in allocation.model_dump().items():
            key = (
                "cpu_millicores"
                if field.startswith("cpu_")
                else "memory_mib"
                if field.startswith("memory_")
                else "workspace_gib"
            )
            bounds = getattr(self, key)
            if not bounds.min <= value <= bounds.max:
                raise ValueError(
                    f"{field} must be between {bounds.min} and {bounds.max}"
                )
        return allocation


def policy(settings):
    return ResourcePolicy.model_validate(json.loads(settings.resource_policy))


def chosen(settings, allocation=None):
    limits = policy(settings)
    allocation = allocation or limits.defaults
    try:
        return limits.validate_allocation(allocation)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def allocation(cr):
    spec = cr["spec"]
    container = next(
        c
        for c in spec["podTemplate"]["spec"]["containers"]
        if c["name"] in {"host", "agent"}
    )
    resources = container["resources"]
    home = next(
        c
        for c in spec["volumeClaimTemplates"]
        if c["metadata"]["name"] in {"home", "workspace"}
    )
    return Allocation(
        cpu_request_millicores=int(parse_quantity(resources["requests"]["cpu"]) * 1000),
        cpu_limit_millicores=int(parse_quantity(resources["limits"]["cpu"]) * 1000),
        memory_request_mib=int(
            parse_quantity(resources["requests"]["memory"]) / (1024**2)
        ),
        memory_limit_mib=int(parse_quantity(resources["limits"]["memory"]) / (1024**2)),
        workspace_gib=int(
            parse_quantity(home["spec"]["resources"]["requests"]["storage"]) / (1024**3)
        ),
    )
