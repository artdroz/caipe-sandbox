"""Profile resource controls expressed in native Kubernetes quantities."""

from decimal import Decimal, DecimalException
from typing import Annotated

from kubernetes.utils.quantity import parse_quantity
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    model_validator,
)

from .resources import Allocation

Quantity = Annotated[str, Field(min_length=1, max_length=64)] | StrictInt | StrictFloat


def units(value, scale, field):
    try:
        number = parse_quantity(value) * scale
        if (
            not number.is_finite()
            or number <= 0
            or number > 2**63 - 1
            or number != number.to_integral_value()
        ):
            raise ValueError
        return int(number)
    except (ValueError, TypeError, DecimalException, OverflowError):
        raise ValueError(
            f"{field} must be positive whole millicores, MiB or GiB"
        ) from None


class ComputeResources(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cpu: Quantity
    memory: Quantity


class ResourceValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requests: ComputeResources
    limits: ComputeResources
    storage: Quantity

    def allocation(self):
        return Allocation(
            cpu_request_millicores=units(self.requests.cpu, 1000, "requests.cpu"),
            cpu_limit_millicores=units(self.limits.cpu, 1000, "limits.cpu"),
            memory_request_mib=units(
                self.requests.memory, Decimal(1) / 1024**2, "requests.memory"
            ),
            memory_limit_mib=units(
                self.limits.memory, Decimal(1) / 1024**2, "limits.memory"
            ),
            workspace_gib=units(self.storage, Decimal(1) / 1024**3, "storage"),
        )


class ResourceControls(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    default: ResourceValues
    minimum: ResourceValues
    maximum: ResourceValues

    @model_validator(mode="after")
    def ordered(self):
        self.validate_allocation(self.default.allocation())
        return self

    def bounds(self):
        low = self.minimum.allocation().model_dump()
        high = self.maximum.allocation().model_dump()
        return {field: {"min": low[field], "max": high[field]} for field in low}

    def validate_allocation(self, size):
        bounds = self.bounds()
        for field, value in size.model_dump().items():
            limits = bounds[field]
            if not limits["min"] <= value <= limits["max"]:
                raise ValueError(f"{field} is outside the profile resource bounds")
        return size


class ProfileUI(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resources: ResourceControls | None = None
