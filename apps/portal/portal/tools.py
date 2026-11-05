"""Read tool sign-in state without returning account details or credentials."""

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from fastapi import HTTPException
from websocket import WebSocketException

from .execution import connect

PROBE = r"""
if ! command -v "$1" >/dev/null 2>&1; then
    printf '%s' 'portal:probe-unavailable' >&2
    exit 127
fi
exec "$@"
"""
PROBE_TIMEOUT = 8
MAX_OUTPUT = 64 * 1024


def probe_command(config):
    return ["/bin/sh", "-c", PROBE, "portal-probe", *config.command]


def probe_state(config, stdout, stderr, returncode):
    if returncode is None:
        return "unknown"
    if returncode == 127 and stderr == "portal:probe-unavailable":
        return "unavailable"
    if config.json_field:
        try:
            value = json.loads(stdout)
        except (ValueError, RecursionError):
            return "unknown"
        for field in config.json_field.split("."):
            value = value.get(field) if isinstance(value, dict) else None
        if isinstance(value, bool):
            return "signed-in" if value else "sign-in"
    elif returncode in config.signed_in_exit_codes:
        return "signed-in"
    elif returncode in config.signed_out_exit_codes or any(
        text.lower() in (stdout + stderr).lower() for text in config.signed_out_contains
    ):
        return "sign-in"
    return "unknown"


def probe_helper(target, helper):
    if helper.status is None:
        return helper.id, "unknown"
    conn = None
    try:
        conn = connect(
            target,
            probe_command(helper.status),
            stdin=False,
            tty=False,
            timeout=PROBE_TIMEOUT,
        )
        deadline = time.monotonic() + PROBE_TIMEOUT
        stdout, stderr = "", ""
        while conn.is_open():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return helper.id, "unknown"
            conn.update(timeout=min(remaining, 1))
            stdout += conn.read_stdout(timeout=0)
            stderr += conn.read_stderr(timeout=0)
            if len(stdout.encode()) + len(stderr.encode()) > MAX_OUTPUT:
                return helper.id, "unknown"
        return helper.id, probe_state(helper.status, stdout, stderr, conn.returncode)
    except (
        HTTPException,
        WebSocketException,
        ValueError,
        OSError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
    ):
        return helper.id, "unknown"
    finally:
        if conn:
            conn.close()


class ToolStatus:
    def __init__(self):
        self.cache = {}
        self.lock = Lock()

    def status(self, target, fresh=False, helpers=()):
        definitions = json.dumps([h.model_dump() for h in helpers], sort_keys=True)
        key = (
            target.key,
            hashlib.sha256(definitions.encode()).hexdigest(),
        )
        with self.lock:
            cached = self.cache.get(key)
        now = time.monotonic()
        if cached and cached[0] > now and not fresh:
            return cached[1]
        result = {h.id: "unknown" for h in helpers}
        if not result:
            return result
        with ThreadPoolExecutor(max_workers=min(8, len(helpers))) as workers:
            result = dict(
                workers.map(lambda helper: probe_helper(target, helper), helpers)
            )
        now = time.monotonic()
        with self.lock:
            self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
            self.cache[key] = (now + 30, result)
        return result
