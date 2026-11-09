"""Hosted HTTP identity and direct terminal authorization use separate keys."""

import json
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from joserfc import jwt
from joserfc.jwk import OctKey
from test_drain import Stream
from test_portal import OTHER, OWNER, SETTINGS, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.auth import Authentication
from portal.integrations.agent_sandbox import execution

KEY = "caipe-test-key-with-at-least-32-bytes"
CAIPE = replace(
    SETTINGS,
    auth_mode="caipe",
    origin="https://caipe.example.com",
    base_path="/apps/sandbox",
    caipe_verification_key=KEY + "\n",
    session_secret="sandbox-test-key-with-at-least-32-bytes",
    terminal_url="wss://terminal.example.com/apps/sandbox",
)


def test_hosted_loading_shell_uses_embedded_layout_before_javascript(hosted):
    browser, *_ = hosted
    page = browser.get("/apps/sandbox/")
    assert page.status_code == 200
    assert '<body class="embedded">' in page.text
    assert 'id="startup"' in page.text
    assert 'src="/apps/sandbox/assets/portal.js"' in page.text


def token(**claims):
    return jwt.encode(
        {"alg": "HS256"},
        {
            "iss": "caipe-agentic-apps",
            "aud": "agentic-app:sandbox",
            "app_id": "sandbox",
            "sub": "caipe-alice",
            "email": OWNER,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            **claims,
        },
        OctKey.import_key(KEY.encode()),
    )


def headers(**claims):
    return {"Origin": CAIPE.origin, "Authorization": "Bearer " + token(**claims)}


@pytest.fixture
def hosted():
    store, kube = store_for(CAIPE)
    app = create_app(CAIPE, store, Omnigent())
    with TestClient(app, base_url=CAIPE.origin) as browser:
        yield browser, store, kube


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "other-host"},
        {"aud": "agentic-app:other"},
        {"app_id": "other"},
        {"exp": 1},
        {"exp": "9999999999"},
        {"exp": float("inf")},
        {"iat": 10**12},
        {"email": None},
        {"email": "invalid"},
        {"sub": ""},
    ],
)
def test_rejects_invalid_caipe_identity(hosted, claims):
    browser, _, _ = hosted
    assert (
        browser.get(
            CAIPE.base_path + "/api/sandboxes", headers=headers(**claims)
        ).status_code
        == 401
    )


def test_headers_cookies_and_invalid_signatures_are_not_identity(hosted):
    browser, _, _ = hosted
    path = CAIPE.base_path + "/api/sandboxes"
    for value in ["", "Bearer broken", "Bearer " + token() + "tampered"]:
        response = browser.get(
            path,
            headers={
                "Authorization": value,
                "X-Caipe-User": OWNER,
                "X-Caipe-Roles": "admin",
                "Cookie": "session=alice",
            },
        )
        assert response.status_code == 401


def test_caipe_authentication_keeps_sandbox_authorization(hosted):
    browser, store, _ = hosted
    own, other = store.create(OWNER), store.create(OTHER)
    path = CAIPE.base_path + "/api"
    result = browser.get(
        path + "/sandboxes", headers=headers(email=OWNER.upper(), roles=["admin"])
    )
    assert result.status_code == 200
    assert result.json()["user_id"] == OWNER
    assert browser.get(path + "/admin/sandboxes", headers=headers()).status_code == 403
    assert browser.post(
        path + f"/sandboxes/{other.name}/terminal-credentials", headers=headers()
    ).status_code in {403, 404}
    assert (
        browser.post(
            path + f"/sandboxes/{own.name}/terminal-credentials", headers=headers()
        ).status_code
        == 200
    )
    assert browser.get(CAIPE.base_path + "/auth/login").status_code == 401
    assert browser.get(CAIPE.base_path + "/auth/config").json() == {
        "mode": "caipe",
        "login_url": None,
        "header_links": json.loads(CAIPE.header_links),
        "terminal_credentials": True,
        "terminal_url": CAIPE.terminal_url,
        "embedded": True,
        "login_message": browser.app.state.auth.hosted.signin_message,
    }
    page = browser.get(CAIPE.base_path + "/")
    assert (
        "connect-src 'self' wss://terminal.example.com;"
        in page.headers["content-security-policy"]
    )


@pytest.mark.parametrize(
    "role,admins,expected",
    [("viewer", [], 403), ("viewer", [OWNER], 201), ("user", [], 201)],
)
def test_sandbox_config_controls_roles(role, admins, expected):
    settings = replace(
        CAIPE,
        caipe_policy=json.dumps({"default_role": role}),
        admin_emails=json.dumps(admins),
    )
    store, _ = store_for(settings)
    with TestClient(
        create_app(settings, store, Omnigent()), base_url=CAIPE.origin
    ) as browser:
        assert (
            browser.post(
                CAIPE.base_path + "/api/sandboxes", headers=headers()
            ).status_code
            == expected
        )


@pytest.mark.parametrize("prefix", ["", "/apps/sandbox", "/nested/apps/sandbox"])
def test_http_handoff_and_direct_socket_work_at_all_prefixes(prefix, monkeypatch):
    settings = replace(CAIPE, base_path=prefix)
    store, _ = store_for(settings)
    sandbox = store.create(OWNER)
    conn = Stream()
    attach = Mock(return_value=conn)
    monkeypatch.setattr(execution, "stream", attach)
    app = create_app(settings, store, Omnigent())
    path = prefix + f"/api/sandboxes/{sandbox.name}/terminal"
    with TestClient(app, base_url=CAIPE.origin) as browser:
        result = browser.post(path + "-credentials", headers=headers())
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["expires_in"] == 30
        # Browser connects directly without CAIPE headers or cookies.
        with browser.websocket_connect(
            path, headers={"Origin": CAIPE.origin, "Sec-Fetch-Site": "cross-site"}
        ) as ws:
            attach.assert_not_called()
            ws.send_json(
                {"type": "authenticate", "credential": result.json()["credential"]}
            )
            assert ws.receive_json(mode="binary") == {"type": "ready"}
            ws.send_json({"type": "input", "data": "echo hello\n"})
            assert conn.received.wait(2)
        attach.assert_called_once()


@pytest.mark.parametrize(
    "change",
    [
        "wrong-vm",
        "helper",
        "owner",
        "admin",
        "uid",
        "expired",
        "invalid",
        "input-first",
        "binary-first",
        "oversized",
    ],
)
def test_terminal_handoff_fails_closed(hosted, monkeypatch, change):
    browser, store, _ = hosted
    sandbox = store.create(OWNER)
    path = CAIPE.base_path + f"/api/sandboxes/{sandbox.name}/terminal"
    result = browser.post(path + "-credentials", headers=headers()).json()
    credential = result["credential"]
    signer = browser.app.state.auth.terminal_credentials.signer
    if change == "wrong-vm":
        path = path.replace(sandbox.name, store.create(OWNER).name)
    elif change in {"helper", "owner"}:
        path += "?" + (
            "helper=claude-login" if change == "helper" else "owner=" + OWNER
        )
    elif change == "admin":
        path = (
            path.replace("/api/", "/api/admin/")
            + "?namespace="
            + sandbox.reference["metadata"]["namespace"]
        )
    elif change in {"uid", "expired"}:
        record = signer.loads(credential)
        if change == "uid":
            record["binding"]["uid"] = "replaced-native-uid"
        else:
            record["identity"]["expires"] = time.time() - 1
        credential = signer.dumps(record)
    elif change == "invalid":
        credential += "broken"
    attach = Mock()
    monkeypatch.setattr(execution, "stream", attach)
    with browser.websocket_connect(path, headers={"Origin": CAIPE.origin}) as ws:
        if change == "input-first":
            ws.send_json({"type": "input", "data": "pwd\n"})
        elif change == "binary-first":
            ws.send_bytes(b"input")
        elif change == "oversized":
            ws.send_text("x" * 8193)
        else:
            ws.send_json({"type": "authenticate", "credential": credential})
        message = ws.receive_json(mode="binary")
        assert message["type"] == "error" and message["code"] in {
            "http-401",
            "http-403",
        }
        assert credential not in str(message)
    attach.assert_not_called()


def test_credentials_work_across_replicas_but_expire(hosted, monkeypatch):
    from portal.terminal_auth import TerminalCredentials

    browser, store, _ = hosted
    sandbox = store.create(OWNER)
    path = CAIPE.base_path + f"/api/sandboxes/{sandbox.name}/terminal"
    credential = browser.post(path + "-credentials", headers=headers()).json()[
        "credential"
    ]
    second = TerminalCredentials(CAIPE.session_secret)
    assert (
        second.signer.loads(credential, max_age=30)["binding"]["name"] == sandbox.name
    )
    later = time.time() + 60
    monkeypatch.setattr(
        "itsdangerous.timed.TimestampSigner.get_timestamp", lambda self: int(later)
    )
    with browser.websocket_connect(path, headers={"Origin": CAIPE.origin}) as ws:
        ws.send_json({"type": "authenticate", "credential": credential})
        assert ws.receive_json(mode="binary")["code"] == "http-401"


def test_missing_authentication_frame_has_a_bounded_wait(hosted, monkeypatch):
    browser, store, _ = hosted
    sandbox = store.create(OWNER)
    path = CAIPE.base_path + f"/api/sandboxes/{sandbox.name}/terminal"
    monkeypatch.setattr("portal.terminal_auth.HANDSHAKE_SECONDS", 0.01)
    with browser.websocket_connect(path, headers={"Origin": CAIPE.origin}) as ws:
        assert ws.receive_json(mode="binary")["code"] == "http-401"


@pytest.mark.parametrize(
    "overrides",
    [
        {"caipe_verification_key": "short"},
        {"session_secret": "short"},
        {"session_secret": KEY},
        {"caipe_policy": '{"default_role":"admin"}'},
    ],
)
def test_hosted_auth_configuration_fails_closed(overrides):
    with pytest.raises(ValueError):
        Authentication(replace(CAIPE, **overrides))


@pytest.mark.parametrize(
    "url",
    [
        "https://shell.example.com",
        "ws://remote.example.com",
        "wss://u:p@shell.example.com",
        "wss://shell.example.com/",
        "wss://shell.example.com/x?q=token",
        "wss://shell.example.com/x#fragment",
        "wss://shell.example.com:invalid/x",
    ],
)
def test_terminal_url_is_validated(monkeypatch, url):
    from portal.config import Settings

    for name, value in CAIPE.__dict__.items():
        monkeypatch.setenv("PORTAL_" + name.upper(), str(value))
    monkeypatch.setenv("PORTAL_TERMINAL_URL", url)
    with pytest.raises(ValueError):
        Settings.from_env()
