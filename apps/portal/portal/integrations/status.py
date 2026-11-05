"""Presentation contract for integrations at any sandbox layer."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntegrationStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    title: str = Field(min_length=1, max_length=80)
    layer: str = Field(min_length=1, max_length=40)
    state: Literal["active", "pending", "inactive", "configured", "unknown", "error"]
    detail: str = Field(default="", max_length=500)
    icon: str = Field(default="box", max_length=40)
    image: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9-]*\.(svg|png|webp|jpe?g)$"
    )
