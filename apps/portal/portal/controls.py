"""Metadata-backed administrative gates and plain-text notices."""

from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
    JsonValue,
)

from .storage import StorageError


class Notice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(default="", max_length=120)
    body: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def complete(self):
        self.title, self.body = self.title.strip(), self.body.strip()
        if self.title and not self.title.isprintable():
            raise ValueError("Message titles must be a single printable line")
        if bool(self.title) != bool(self.body):
            raise ValueError(
                "A message needs both a title and body, or neither to clear it"
            )
        return self


class StoredNotice(Notice):
    author: str = ""
    updated_at: str = ""


class UserControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    creation_disabled: bool = False
    sandboxes_disabled: bool = False
    reason: str = Field(default="", max_length=500)


class NamespaceControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    creation_disabled: bool = False
    network_policy: dict[str, JsonValue] | None = None


class NamespaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resource_version: str = Field(min_length=1, max_length=100)
    locked: bool


class GlobalPolicy(UserControl):
    announcement: StoredNotice | None = None
    users: dict[str, UserControl] = Field(default_factory=dict, max_length=200)
    namespaces: dict[str, NamespaceControl] = Field(
        default_factory=dict, max_length=1000
    )
    updated_by: str = ""
    updated_at: str = ""

    @field_validator("users")
    @classmethod
    def emails(cls, value):
        import re

        if any(
            len(email) > 254
            or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)
            or email != email.lower()
            for email in value
        ):
            raise ValueError("Use lowercase user email addresses")
        return value


class GlobalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resource_version: str = Field(min_length=1, max_length=100)
    creation_disabled: bool
    sandboxes_disabled: bool
    reason: str = Field(default="", max_length=500)
    announcement: Notice = Field(default_factory=Notice)
    users: dict[str, UserControl] = Field(default_factory=dict, max_length=200)

    @field_validator("users")
    @classmethod
    def emails(cls, value):
        return GlobalPolicy.emails(value)


class SandboxControl(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    disabled: bool = False
    reason: str = Field(default="", max_length=500)
    notice: StoredNotice | None = None
    updated_by: str = ""
    updated_at: str = ""


class SandboxUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    resource_version: str = Field(min_length=1, max_length=100)
    disabled: bool | None = None
    reason: str | None = Field(default=None, max_length=500)
    notice: Notice | None = None
    operating_mode: str | None = None

    @field_validator("operating_mode")
    @classmethod
    def mode(cls, value):
        if value not in {None, "Running", "Suspended"}:
            raise ValueError("Choose Running or Suspended")
        return value


def now():
    return datetime.now(UTC).isoformat()


def notice(value, actor):
    return (
        StoredNotice(**value.model_dump(), author=actor, updated_at=now())
        if value.title
        else None
    )


def sandbox_control(sandbox):
    if sandbox.control is None:
        raise HTTPException(
            503, "Sandbox administrative metadata is invalid; contact an administrator"
        )
    return sandbox.control


def disabled(cr, policy):
    local = sandbox_control(cr)
    owner = cr.owner
    user = policy.users.get(owner, UserControl())
    for blocked, reason in [
        (policy.sandboxes_disabled, policy.reason),
        (user.sandboxes_disabled, user.reason),
        (local.disabled, local.reason),
    ]:
        if blocked:
            return reason or "Sandbox access has been disabled by an administrator"
    return ""


def creation_blocked(owner, policy):
    user = policy.users.get(owner, UserControl())
    if policy.creation_disabled or policy.sandboxes_disabled:
        return policy.reason or "Sandbox creation has been disabled by an administrator"
    if user.creation_disabled or user.sandboxes_disabled:
        return user.reason or "Sandbox creation has been disabled for your account"
    return ""


class Controls:
    def __init__(self, metadata):
        self.metadata = metadata

    def read(self):
        record = self.metadata.get_controls()
        try:
            return GlobalPolicy.model_validate(record.policy), str(record.revision)
        except ValidationError:
            raise StorageError("Portal administrative metadata is invalid") from None

    def save(self, update, actor):
        previous, version = self.read()
        if version != update.resource_version:
            raise HTTPException(409, "Admin controls changed; refresh and retry")
        policy = GlobalPolicy(
            creation_disabled=update.creation_disabled,
            sandboxes_disabled=update.sandboxes_disabled,
            reason=update.reason,
            users=update.users,
            namespaces=previous.namespaces,
            announcement=notice(update.announcement, actor),
            updated_by=actor,
            updated_at=now(),
        )
        record = self.metadata.save_controls(
            policy.model_dump(mode="json"), expected_revision=int(version)
        )
        return policy, str(record.revision)
