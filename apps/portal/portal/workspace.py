"""Bounded workspace operations through the engineering image's control command."""

import json
import time
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from websocket import WebSocketException

from .execution import connect

MAX_OUTPUT = 256 * 1024
EXEC_TIMEOUT = 15


class WorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "read",
        "save",
        "delete",
        "apply",
        "preview",
        "read-version",
        "restore",
        "start",
        "stop",
        "restart",
        "logs",
        "startup-logs",
    ]
    kind: Literal["startup", "service"] | None = None
    name: str | None = Field(
        default=None, max_length=70, pattern=r"^[a-z0-9][a-z0-9._-]*\.(sh|conf)$"
    )
    content: str | None = Field(default=None, max_length=65536)
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source: Literal["applied", "previous", "default"] | None = None
    source_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    preview_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    service: str | None = Field(
        default=None, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )


class Workspace:
    def run(self, target, body):
        conn = None
        try:
            conn = connect(
                target,
                ["/usr/local/bin/sandbox-control"],
                stdin=True,
                tty=False,
                timeout=EXEC_TIMEOUT,
            )
            conn.write_stdin(json.dumps(body) + "\n")
            deadline = time.monotonic() + EXEC_TIMEOUT
            stdout = ""
            received = 0
            while conn.is_open():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HTTPException(
                        504,
                        "micro VM operation timed out; refresh its status before retrying",
                    )
                conn.update(timeout=min(remaining, 1))
                chunk = conn.read_stdout(timeout=0)
                stderr = conn.read_stderr(timeout=0)
                received += len(chunk.encode()) + len(stderr.encode())
                stdout += chunk
                if received > MAX_OUTPUT:
                    raise HTTPException(
                        502, "micro VM response exceeded its size limit"
                    )
            if conn.returncode:
                raise HTTPException(
                    501,
                    "This image does not provide Startup & services. Select an image with sandbox-start and sandbox-control support.",
                )
            data = json.loads(stdout)
            if not isinstance(data, dict):
                raise ValueError("Invalid response")
            if "error" in data:
                code = data.get("code")
                raise HTTPException(
                    code if code in {404, 409, 422, 503} else 502,
                    str(data["error"])[:500],
                )
            if body.get("action") == "inspect" and data.get("protocol_version") != 1:
                raise HTTPException(
                    501,
                    "This image uses an unsupported Startup & services protocol version",
                )
            return data
        except (
            WebSocketException,
            OSError,
            ValueError,
            TypeError,
        ):
            raise HTTPException(
                503,
                "micro VM service is unavailable; check that the sandbox is running a supported engineering image",
            ) from None
        finally:
            if conn:
                conn.close()
