"""Short-lived, resource-bound authorization for browser WebSocket handoff."""

import asyncio
import hashlib
import json
import time

from fastapi import HTTPException
from itsdangerous import BadData, URLSafeTimedSerializer

REDEEM_SECONDS = 30
HANDSHAKE_SECONDS = 5


class TerminalCredentials:
    def __init__(self, secret):
        if len(secret.encode()) < 32:
            raise ValueError(
                "Terminal handoff requires a session secret of at least 32 bytes"
            )
        self.signer = URLSafeTimedSerializer(
            secret,
            salt="sandbox-terminal-v1",
            signer_kwargs={"digest_method": hashlib.sha256},
        )

    def issue(self, identity, binding):
        return {
            "credential": self.signer.dumps({"identity": identity, "binding": binding}),
            "expires_in": REDEEM_SECONDS,
        }

    async def accept(self, ws):
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=HANDSHAKE_SECONDS)
            if len(raw) > 8192:
                raise ValueError("Oversized authentication message")
            message = json.loads(raw)
            if not isinstance(message, dict) or message.get("type") != "authenticate":
                raise ValueError("Authentication must precede terminal input")
            record = self.signer.loads(message["credential"], max_age=REDEEM_SECONDS)
            if record["identity"]["expires"] <= time.time():
                raise ValueError("Session expired")
        except (BadData, ValueError, TypeError, KeyError, TimeoutError):
            raise HTTPException(
                401, "Terminal authorization expired; reconnect from Sandbox"
            ) from None
        ws.state.terminal_identity = record["identity"]
        ws.state.terminal_binding = record["binding"]

    @staticmethod
    def check(ws, binding):
        if getattr(ws.state, "terminal_binding", None) != binding:
            raise HTTPException(
                403,
                "Terminal authorization does not match this micro VM or helper; reconnect",
            )
