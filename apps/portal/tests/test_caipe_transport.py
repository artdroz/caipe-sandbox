"""Exercise the HTTP-only host proxy and direct WebSocket over real sockets."""

import json
import re
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
import websocket
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from test_caipe import CAIPE, token
from test_drain import Stream
from test_portal import OWNER, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.integrations.agent_sandbox import execution


@contextmanager
def running(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, lifespan="on"))
        thread = threading.Thread(
            target=lambda: server.run(sockets=[listener]), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test server did not start")
            time.sleep(0.01)
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            assert not thread.is_alive(), "Test server did not stop"


def host_proxy(upstream):
    host = FastAPI()

    @host.api_route("/{path:path}", methods=["GET", "POST"])
    async def forward(request: Request, path: str):
        if path and request.url.path.endswith("/"):
            return RedirectResponse(
                str(request.url.replace(path=request.url.path.rstrip("/"))),
                status_code=308,
            )
        forwarded = {
            k: v
            for k, v in request.headers.items()
            if k not in {"host", "cookie", "authorization", "content-length"}
            and not k.startswith("x-caipe-")
        }
        forwarded["authorization"] = "Bearer " + token()
        async with httpx.AsyncClient() as client:
            result = await client.request(
                request.method,
                upstream + request.url.path,
                params=request.query_params,
                headers=forwarded,
                content=await request.body(),
            )
        return Response(
            result.content,
            status_code=result.status_code,
            headers={
                k: v
                for k, v in result.headers.items()
                if k.lower()
                not in {
                    "content-length",
                    "content-encoding",
                    "set-cookie",
                    "connection",
                }
            },
        )

    return host


@pytest.mark.parametrize("prefix", ["", "/apps/sandbox", "/nested/apps/sandbox"])
def test_http_proxy_then_direct_terminal(prefix, monkeypatch):
    settings = replace(CAIPE, base_path=prefix)
    store, _ = store_for(settings)
    sandbox = store.create(OWNER)
    conn = Stream()
    monkeypatch.setattr(execution, "stream", Mock(return_value=conn))
    path = prefix + f"/api/sandboxes/{sandbox.name}/terminal"
    with (
        running(create_app(settings, store, Omnigent())) as upstream,
        running(host_proxy(upstream)) as proxy,
    ):
        # Host strips an untrusted browser identity and supplies its own signed JWT.
        response = httpx.get(
            proxy + prefix + "/api/sandboxes",
            headers={
                "Authorization": "untrusted",
                "X-Caipe-User": "attacker@example.com",
            },
        )
        assert response.status_code == 200
        assert response.json()["user_id"] == OWNER
        page = httpx.get(proxy + prefix + "/", follow_redirects=True)
        assert page.status_code == 200
        assert len(page.history) == (1 if prefix else 0)
        assert str(page.url).startswith(proxy + "/")
        for pattern in (
            r'<script[^>]+src="([^"]+)"',
            r'<link[^>]+href="([^"]+portal\.css[^"]*)"',
        ):
            asset = re.search(pattern, page.text).group(1)
            assert httpx.get(page.url.join(asset)).status_code == 200
        assert httpx.get(upstream + prefix + "/api/sandboxes").status_code == 401
        result = httpx.post(
            proxy + path + "-credentials", headers={"Origin": settings.origin}
        )
        assert result.status_code == 200, result.text
        # No WebSocket implementation exists on the HTTP proxy.
        with pytest.raises(websocket.WebSocketBadStatusException):
            websocket.create_connection(
                proxy.replace("http:", "ws:") + path, origin=settings.origin, timeout=2
            )
        ws = websocket.create_connection(
            upstream.replace("http:", "ws:") + path, origin=settings.origin, timeout=5
        )
        try:
            ws.send(
                json.dumps(
                    {"type": "authenticate", "credential": result.json()["credential"]}
                )
            )
            assert ws.recv() == b'{"type":"ready"}'
            ws.send(json.dumps({"type": "input", "data": "echo proxy boundary\n"}))
            assert conn.received.wait(2)
        finally:
            ws.close()
        assert conn.closed.wait(2)
