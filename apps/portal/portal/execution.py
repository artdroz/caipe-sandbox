"""Execution targets supplied by an authorized sandbox integration."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from fastapi import HTTPException


class ExecutionStream(Protocol):
    returncode: int | None

    def is_open(self) -> bool: ...
    def update(self, timeout: float) -> None: ...
    def read_all(self) -> str: ...
    def read_stdout(self, timeout: float = 0) -> str: ...
    def read_stderr(self, timeout: float = 0) -> str: ...
    def write_stdin(self, data: str) -> None: ...
    def write_channel(self, channel: int, data: str) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class ExecutionTarget:
    key: tuple[str, ...]
    scope: str
    sandbox_uid: str
    connector: Callable[..., ExecutionStream] = field(repr=False)
    default_command: tuple[str, ...] | None = None


def connect(target, command, *, stdin=True, tty=False, timeout=15):
    if not isinstance(target, ExecutionTarget):
        raise HTTPException(
            409, "Sandbox execution transport is unavailable; execution is blocked"
        )
    return target.connector(command, tty=tty, stdin=stdin, timeout=timeout)
