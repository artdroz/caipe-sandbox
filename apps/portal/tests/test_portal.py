import base64
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from inventory_fakes import native_view as view
from kubernetes.client import ApiException

from portal.app import create_app
from portal.config import Settings
from portal.integrations.agent_sandbox import execution
from portal.integrations.agent_sandbox.inventory import PREFIX, manifest, sandbox_name
from portal.namespaces import UserNamespaces, namespace_name
from portal.resources import DEFAULT_POLICY
from portal.sandboxes import Store
from portal.storage import open_store
from portal.storage.database import DatabaseSettings

OWNER = "alice@example.com"
OTHER = "bob@example.com"

PROFILE_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures/profiles.json").read_text()
)
SETTINGS = Settings(
    auth_mode="omnigent",
    auth_omnigent_url="http://omnigent:8000",
    profiles=json.dumps(PROFILE_FIXTURES),
    default_profile="development",
    runtime_class="kata-dev",
    namespace='{"strategy":"perUser"}',
    namespace_policy='{"podSecurityVersion":"latest","baselineNetworkPolicy":true,"quota":{},"extraEgress":[],"deleteWhenEmpty":false}',
)
BASE = SETTINGS.base_path + "/api"
HEADERS = {"Origin": SETTINGS.origin, "Cookie": "session=alice"}


class Kubernetes:
    def __init__(self):
        self.metadata_directory = TemporaryDirectory(prefix="portal-test-")
        self.metadata = open_store(
            DatabaseSettings(
                url=f"sqlite:///{self.metadata_directory.name}/metadata.db"
            )
        )
        self.metadata.migrate()
        self.items = {}
        self.secrets = {}
        self.configmaps = {}
        self.namespace_objects = {}
        self.baseline = {}

    def create_namespace(self, body):
        name = body["metadata"]["name"]
        if name in self.namespace_objects:
            raise ApiException(409)
        self.namespace_objects[name] = deepcopy(body)
        self.namespace_objects[name]["metadata"].update(
            uid="namespace-uid",
            resourceVersion="1",
            creationTimestamp="2026-01-01T00:00:00Z",
        )

    def read_namespace(self, name):
        if name not in self.namespace_objects:
            raise ApiException(404)
        return deepcopy(self.namespace_objects[name])

    def list_namespace(self, label_selector, limit=None, _continue=None):
        items = []
        for namespace in self.namespace_objects.values():
            labels = namespace["metadata"].get("labels", {})
            matches = all(
                (part[1:] not in labels)
                if part.startswith("!")
                else labels.get(part.split("=", 1)[0]) == part.split("=", 1)[1]
                for part in label_selector.split(",")
            )
            if matches:
                items.append(deepcopy(namespace))
        return SimpleNamespace(items=items, metadata=SimpleNamespace(_continue=None))

    def list_namespaced_persistent_volume_claim(self, namespace, **kwargs):
        return SimpleNamespace(items=[])

    def list_namespaced_pod(self, namespace, **kwargs):
        return SimpleNamespace(items=[])

    def list_namespaced_secret(self, namespace):
        return SimpleNamespace(
            items=[
                secret
                for secret in self.secrets.values()
                if secret.metadata.namespace == namespace
            ]
        )

    def create_baseline(self, namespace, body):
        key = (body["kind"], namespace, body["metadata"]["name"])
        if key in self.baseline:
            raise ApiException(409)
        self.baseline[key] = deepcopy(body)

    def read_baseline(self, kind, name, namespace):
        try:
            return deepcopy(self.baseline[(kind, namespace, name)])
        except KeyError:
            raise ApiException(404) from None

    create_namespaced_service_account = create_baseline
    create_namespaced_resource_quota = create_baseline

    def create_namespaced_network_policy(self, namespace, body, **kwargs):
        if kwargs.get("dry_run") == "All":
            return deepcopy(body)
        value = deepcopy(body)
        value["metadata"].update(
            uid="policy-" + body["metadata"]["name"], resourceVersion="1"
        )
        self.create_baseline(namespace, value)
        return deepcopy(value)

    def list_namespaced_network_policy(self, namespace, **kwargs):
        return SimpleNamespace(
            items=[
                deepcopy(value)
                for (kind, ns, _), value in self.baseline.items()
                if kind == "NetworkPolicy" and ns == namespace
            ],
            metadata=SimpleNamespace(_continue=None),
        )

    def replace_namespaced_network_policy(self, name, namespace, body, **kwargs):
        key = ("NetworkPolicy", namespace, name)
        current = self.baseline[key]
        if (
            body["metadata"].get("resourceVersion")
            != current["metadata"]["resourceVersion"]
        ):
            raise ApiException(409)
        if kwargs.get("dry_run") == "All":
            return deepcopy(body)
        value = deepcopy(body)
        value["metadata"]["resourceVersion"] = str(
            int(current["metadata"]["resourceVersion"]) + 1
        )
        self.baseline[key] = value
        return deepcopy(value)

    create_namespaced_role_binding = create_baseline

    def read_namespaced_service_account(self, name, namespace):
        return self.read_baseline("ServiceAccount", name, namespace)

    def read_namespaced_resource_quota(self, name, namespace):
        return self.read_baseline("ResourceQuota", name, namespace)

    def patch_namespaced_network_policy(self, name, namespace, body):
        self.baseline[("NetworkPolicy", namespace, name)]["spec"]["egress"] = deepcopy(
            body["spec"]["egress"]
        )

    def read_namespaced_network_policy(self, name, namespace):
        return self.read_baseline("NetworkPolicy", name, namespace)

    def read_namespaced_role_binding(self, name, namespace):
        return self.read_baseline("RoleBinding", name, namespace)

    def create_namespaced_custom_object(
        self,
        group,
        version,
        namespace,
        plural,
        body,
        dry_run=None,
        field_validation=None,
    ):
        if dry_run == "All":
            return deepcopy(body)
        name = body["metadata"]["name"]
        if (namespace, name) in self.items:
            raise ApiException(409)
        cr = deepcopy(body)
        cr["metadata"].update(
            uid="uid-" + namespace + "-" + name, resourceVersion="1", generation=1
        )
        self.items[(namespace, name)] = cr
        return deepcopy(cr)

    def get_namespaced_custom_object(
        self, group, version, namespace, plural, name, **kwargs
    ):
        if (namespace, name) not in self.items or self.items[(namespace, name)][
            "metadata"
        ]["namespace"] != namespace:
            raise ApiException(404)
        return deepcopy(self.items[(namespace, name)])

    def list_namespaced_custom_object(
        self,
        group,
        version,
        namespace,
        plural,
        label_selector="",
        limit=None,
        _continue=None,
    ):
        labels = dict(pair.split("=", 1) for pair in label_selector.split(",") if pair)
        return {
            "items": [
                deepcopy(cr)
                for cr in self.items.values()
                if cr["metadata"]["namespace"] == namespace
                and all(cr["metadata"]["labels"].get(k) == v for k, v in labels.items())
            ]
        }

    def patch_namespaced_custom_object(
        self, group, version, namespace, plural, name, body, **kwargs
    ):
        cr = self.items[(namespace, name)]
        if body["metadata"]["resourceVersion"] != cr["metadata"]["resourceVersion"] or (
            body["metadata"].get("uid", cr["metadata"]["uid"]) != cr["metadata"]["uid"]
        ):
            raise ApiException(409)

        def merge(target, patch):
            for key, value in patch.items():
                if isinstance(value, dict):
                    merge(target.setdefault(key, {}), value)
                elif value is None:
                    target.pop(key, None)
                else:
                    target[key] = deepcopy(value)

        if "spec" in body:
            merge(cr["spec"], body["spec"])
            cr["metadata"]["generation"] += 1
        merge(cr["metadata"], body["metadata"])
        cr["metadata"]["resourceVersion"] = str(
            int(cr["metadata"]["resourceVersion"]) + 1
        )
        return deepcopy(cr)

    def delete_namespaced_custom_object(
        self, group, version, namespace, plural, name, body
    ):
        cr = self.items[(namespace, name)]
        assert body["preconditions"]["uid"] == cr["metadata"]["uid"]
        del self.items[(namespace, name)]

    def read_namespaced_secret(self, name, namespace):
        if name not in self.secrets:
            raise ApiException(404)
        return self.secrets[name]

    def save_secret(self, body):
        self.secrets[body["metadata"]["name"]] = SimpleNamespace(
            metadata=SimpleNamespace(
                resource_version="1",
                namespace=body["metadata"]["namespace"],
                owner_references=[
                    SimpleNamespace(uid=body["metadata"]["ownerReferences"][0]["uid"])
                ],
            ),
            data={
                k: base64.b64encode(v.encode()).decode()
                for k, v in body["stringData"].items()
            },
        )

    def create_namespaced_secret(self, namespace, body):
        if body["metadata"]["name"] in self.secrets:
            raise ApiException(409)
        self.save_secret(body)

    def replace_namespaced_secret(self, name, namespace, body):
        self.save_secret(body)

    def read_namespaced_pod(self, name, namespace):
        cr = self.items.get((namespace, name))
        if (
            cr
            and cr["spec"].get("operatingMode") == "Suspended"
            and view(cr)["state"] == "Suspended"
        ):
            raise ApiException(404)
        return SimpleNamespace(
            status=SimpleNamespace(phase="Running"),
            metadata=SimpleNamespace(
                namespace=namespace,
                name=name,
                uid="pod-uid-" + name,
                owner_references=[
                    SimpleNamespace(uid=cr["metadata"]["uid"] if cr else "missing")
                ],
            ),
        )


class Omnigent:
    def __init__(self):
        self.login_owner = OWNER
        self.hosts = []
        self.hosts_down = False

    async def get(self, path, headers=None, params=None):
        if path == "/v1/me":
            cookie = (headers or {}).get("cookie", "")
            if cookie == "session=alice":
                return httpx.Response(200, json={"user_id": OWNER})
            if cookie == "session=bob":
                return httpx.Response(200, json={"user_id": OTHER})
            if cookie == "session=local":
                return httpx.Response(200, json={"user_id": None})
            return httpx.Response(401, json={})
        if path == "/v1/hosts":
            return httpx.Response(
                503 if self.hosts_down else 200,
                json={
                    "hosts": []
                    if "session=bob" in (headers or {}).get("cookie", "")
                    else self.hosts
                },
            )
        if path == "/auth/cli-poll":
            return httpx.Response(
                200,
                json={
                    "token": "test-bearer",
                    "refresh_token": "test-refresh",
                    "user_id": self.login_owner,
                    "expires_in": 3600,
                },
            )
        raise AssertionError(path)

    async def post(self, path):
        assert path == "/auth/cli-login"
        return httpx.Response(
            200,
            json={
                "ticket": "test-ticket",
                "login_url": "/auth/login?ticket=test-ticket",
            },
        )


@pytest.fixture
def setup():
    kube, upstream = Kubernetes(), Omnigent()
    store = Store(
        SETTINGS,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(SETTINGS, kube, kube, kube),
        metadata=kube.metadata,
    )
    with TestClient(create_app(SETTINGS, store, upstream)) as browser:
        yield browser, store, kube, upstream


def test_branding_and_logo_are_available_before_signin(setup):
    browser, _, _, _ = setup
    prefix = BASE.removesuffix("/api")
    page = browser.get(prefix + "/")
    assert page.status_code == 200
    assert "<title>CAIPE Sandbox</title>" in page.text
    assert f'href="{prefix}/assets/caipe-sandbox-logo.png"' in page.text
    logo = browser.get(prefix + "/assets/caipe-sandbox-logo.png")
    assert logo.status_code == 200
    assert logo.headers["content-type"] == "image/png"
    assert logo.headers["x-content-type-options"] == "nosniff"
    assert logo.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert browser.get(prefix + "/assets/app.py").status_code == 404


def test_initial_page_shows_public_loading_shell_without_account_or_inventory(setup):
    from html.parser import HTMLParser

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.by_id = {}

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if "id" in attributes:
                self.by_id[attributes["id"]] = attributes

    browser, _, _, _ = setup
    page = browser.get(BASE.removesuffix("/api") + "/")
    elements = Elements()
    elements.feed(page.text)
    assert "hidden" not in elements.by_id["app-main"]
    assert "hidden" not in elements.by_id["startup"]
    assert "hidden" in elements.by_id["account"]
    assert "hidden" in elements.by_id["inventory-content"]
    assert "hidden" in elements.by_id["admin-nav"]
    assert "disabled" in elements.by_id["new-sandbox"]
    assert "__PORTAL_BODY_CLASS__" not in page.text
    assert '<body class="">' in page.text


def test_terminal_runtime_is_available_at_the_portal_prefix_on_retry(setup, tmp_path, monkeypatch):
    import portal.app as portal_app

    browser, _, _, _ = setup
    script = "export class Terminal {}"
    (tmp_path / "terminal-runtime.js").write_text(script)
    monkeypatch.setattr(portal_app, "STATIC", tmp_path)
    response = browser.get(BASE.removesuffix("/api") + "/assets/terminal-runtime.js?retry=1")
    assert response.status_code == 200
    assert response.text == script
    assert "javascript" in response.headers["content-type"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_create_is_idempotent_and_owner_is_server_derived(setup):
    browser, _store, kube, _ = setup
    request_id = str(uuid4())
    body = {"owner": OTHER, "title": "Frontend", "request_id": request_id}
    assert (
        browser.post(BASE + "/sandboxes", headers=HEADERS, json=body).status_code == 422
    )
    body.pop("owner")
    first = browser.post(BASE + "/sandboxes", headers=HEADERS, json=body)
    second = browser.post(BASE + "/sandboxes", headers=HEADERS, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"] == sandbox_name(request_id)
    assert first.json()["owner"] == OWNER
    assert len(kube.items) == 1


@pytest.mark.parametrize("cookie", ["", "session=local"])
def test_unauthenticated_or_auth_disabled_mode_rejected(setup, cookie):
    browser, _, kube, _ = setup
    assert (
        browser.post(
            BASE + "/sandboxes", headers={"Origin": SETTINGS.origin, "Cookie": cookie}
        ).status_code
        == 401
    )
    assert not kube.items


@pytest.mark.parametrize("origin", [None, "https://attacker.example", "null"])
def test_mutations_reject_cross_origin(setup, origin):
    browser, _, kube, _ = setup
    headers = {"Cookie": "session=alice"}
    if origin:
        headers["Origin"] = origin
    assert browser.post(BASE + "/sandboxes", headers=headers).status_code == 403
    assert not kube.items


def test_list_is_scoped_to_authenticated_user(setup):
    browser, store, _, _ = setup
    store.create(OWNER).reference
    store.create(OTHER).reference
    response = browser.get(BASE + "/sandboxes", headers=HEADERS)
    assert [s["owner"] for s in response.json()["sandboxes"]] == [OWNER]


@pytest.mark.parametrize(
    "action,method",
    [
        ("suspend", "POST"),
        ("resume", "POST"),
        ("", "DELETE"),
    ],
)
def test_other_user_cannot_access_sandbox(setup, action, method):
    browser, store, _, _ = setup
    cr = store.create(OTHER).reference
    path = (
        BASE + "/sandboxes/" + cr["metadata"]["name"] + ("/" + action if action else "")
    )
    assert browser.request(method, path, headers=HEADERS).status_code == 404


def test_native_owner_annotation_does_not_override_database_owner(setup):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    kube.items[(cr["metadata"]["namespace"], cr["metadata"]["name"])]["metadata"][
        "annotations"
    ][PREFIX + "owner"] = OTHER
    assert (
        browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"][0][
            "owner"
        ]
        == OWNER
    )
    assert (
        browser.get(
            BASE + "/sandboxes", headers={**HEADERS, "Cookie": "session=bob"}
        ).json()["sandboxes"]
        == []
    )


def test_suspend_resume_preserves_identity_and_pvc(setup):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    claim = deepcopy(cr["spec"]["volumeClaimTemplates"])
    before = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"][0]
    refreshed = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"][0]
    assert refreshed["created_at"] == before["created_at"]
    assert refreshed["updated_at"] == before["updated_at"]
    assert (
        browser.post(BASE + f"/sandboxes/{name}/suspend", headers=HEADERS).json()[
            "state"
        ]
        == "Suspending"
    )
    assert (
        browser.post(BASE + f"/sandboxes/{name}/resume", headers=HEADERS).json()[
            "state"
        ]
        == "Provisioning"
    )
    assert (
        kube.items[(namespace_name(SETTINGS, OWNER), name)]["spec"][
            "volumeClaimTemplates"
        ]
        == claim
    )
    after = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"][0]
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] > before["updated_at"]


def test_stale_ready_condition_not_reported_running():
    cr = manifest(SETTINGS, OWNER)
    cr["metadata"]["generation"] = 2
    cr["status"] = {
        "conditions": [{"type": "Ready", "status": "True", "observedGeneration": 1}]
    }
    assert view(cr)["state"] == "Provisioning"
    cr["status"]["conditions"][0]["observedGeneration"] = 2
    assert view(cr)["state"] == "Running"


def test_pod_uid_checked_before_terminal_attach(setup):
    _, store, kube, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    kube.items[(namespace_name(SETTINGS, OWNER), name)]["metadata"]["uid"] = (
        "different-uid"
    )
    with pytest.raises(Exception) as exc:
        store.execution(name, OWNER)
    assert exc.value.status_code == 409


def test_websocket_rejects_cross_origin_before_accept(setup):
    browser, store, _, _ = setup
    from starlette.websockets import WebSocketDisconnect

    name = store.create(OWNER).reference["metadata"]["name"]
    with (
        pytest.raises(WebSocketDisconnect),
        browser.websocket_connect(
            BASE + f"/sandboxes/{name}/terminal",
            headers={"Origin": "https://attacker.example", "Cookie": "session=alice"},
        ),
    ):
        pass


def test_kubernetes_error_does_not_echo_secrets(setup):
    browser, store, _, _ = setup
    store.create = Mock(
        side_effect=ApiException(status=403, reason="test-bearer secret")
    )
    response = browser.post(BASE + "/sandboxes", headers=HEADERS)
    assert response.status_code == 503
    assert "test-bearer" not in response.text


def test_operator_template_is_unprivileged_and_no_sa_token():
    body = manifest(SETTINGS, OWNER)
    pod = body["spec"]["podTemplate"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["runtimeClassName"] == SETTINGS.runtime_class
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["containers"][0]["securityContext"]["capabilities"]["drop"] == ["ALL"]


def test_terminal_streams_input_output_and_resize_for_owner(setup, monkeypatch):
    import io
    import threading

    from kubernetes.stream.ws_client import WSClient

    browser, store, _, _ = setup
    name = store.create(OWNER).reference["metadata"]["name"]
    received_input, received_resize, closed = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    class Exec(WSClient):
        opened = True
        input = None
        size = None

        def __init__(self):
            self._all = io.StringIO("$ ")
            self._channels = {1: "$ "}

        def is_open(self):
            return self.opened

        def update(self, timeout):
            assert timeout is not None, "Idle TTY reads must not wait indefinitely"

        def write_stdin(self, data):
            self.input = data
            self._all.write(data)
            received_input.set()

        def write_channel(self, channel, data):
            assert channel == 4
            self.size = json.loads(data)
            received_resize.set()

        def close(self):
            self.opened = False
            closed.set()

    terminal = Exec()

    def attach(*args, **kwargs):
        assert kwargs["command"] == [
            "env",
            "TERM=xterm-256color",
            "COLORTERM=truecolor",
            "bash",
            "-l",
        ]
        assert kwargs["tty"] and kwargs["stdin"]
        return terminal

    monkeypatch.setattr(execution, "stream", attach)
    with browser.websocket_connect(
        BASE + f"/sandboxes/{name}/terminal", headers=HEADERS
    ) as ws:
        assert ws.receive_json(mode="binary") == {"type": "ready"}
        assert ws.receive_text() == "$ "
        assert browser.get("/healthz").status_code == 200
        ws.send_json({"type": "input", "data": "pwd\n"})
        assert received_input.wait(2)
        assert terminal.input == "pwd\n"
        assert ws.receive_text() == "pwd\n"
        ws.send_json({"type": "resize", "cols": 80, "rows": 24})
        assert received_resize.wait(2)
        assert terminal.size == {"Width": 80, "Height": 24}
    assert closed.wait(2)
    assert not terminal.opened


def test_stale_suspended_condition_not_reported_complete():
    cr = manifest(SETTINGS, OWNER)
    cr["metadata"]["generation"] = 4
    cr["spec"]["operatingMode"] = "Suspended"
    cr["status"] = {
        "conditions": [{"type": "Suspended", "status": "True", "observedGeneration": 2}]
    }
    assert view(cr)["state"] == "Suspending"
    cr["status"]["conditions"][0]["observedGeneration"] = 4
    assert view(cr)["state"] == "Suspended"


def test_user_can_create_multiple_independent_named_sandboxes(setup):
    browser, _, kube, _ = setup
    rows = [
        browser.post(BASE + "/sandboxes", headers=HEADERS, json={"title": title}).json()
        for title in ("Frontend", "Backend", "Frontend")
    ]
    assert len({r["id"] for r in rows}) == 3
    assert all("host_id" not in row for row in rows)
    assert {r["namespace"] for r in rows} == {namespace_name(SETTINGS, OWNER)}
    assert [r["title"] for r in rows] == ["Frontend", "Backend", "Frontend"]
    assert len(kube.items) == 3
    assert (
        len(browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"]) == 3
    )


def test_users_get_separate_namespaces_and_owner_annotations(setup):
    _, store, kube, _ = setup
    a, b = store.create(OWNER).reference, store.create(OTHER).reference
    assert a["metadata"]["namespace"] != b["metadata"]["namespace"]
    for owner in (OWNER, OTHER):
        ns = kube.namespace_objects[namespace_name(SETTINGS, owner)]
        assert ns["metadata"]["annotations"][PREFIX + "owner"] == owner
        assert (
            ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"]
            == "restricted"
        )
        assert len(store.list(owner)) == 1


def test_namespace_names_are_valid_and_collision_resistant():
    import re

    name = namespace_name(SETTINGS, "User.Name+Test@Example.COM")
    assert name.startswith("agent-user-name-test-example-com-")
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", name)
    assert len(namespace_name(SETTINGS, "a" * 200 + "@example.com")) <= 63
    assert namespace_name(SETTINGS, "a.b@example.com") != namespace_name(
        SETTINGS, "a-b@example.com"
    )


def test_namespace_baseline_blocks_ingress_and_private_egress_before_cr(setup):
    _, store, kube, _ = setup
    store.create(OWNER).reference
    ns = namespace_name(SETTINGS, OWNER)
    network = kube.baseline[("NetworkPolicy", ns, "sandbox-isolation")]["spec"]
    assert network["podSelector"] == {}
    assert network["policyTypes"] == ["Ingress", "Egress"]
    assert network["ingress"] == []
    assert "169.254.0.0/16" in network["egress"][1]["to"][0]["ipBlock"]["except"]
    binding = kube.baseline[("RoleBinding", ns, "sandbox-portal-access")]
    assert binding["roleRef"]["name"] == SETTINGS.namespace_access_role
    assert binding["subjects"] == [
        {
            "kind": "ServiceAccount",
            "name": SETTINGS.portal_service_account,
            "namespace": SETTINGS.portal_namespace,
        }
    ]


def test_existing_namespace_owner_or_policy_conflict_is_not_adopted(setup):
    _, store, kube, _ = setup
    store.create(OWNER).reference
    ns = namespace_name(SETTINGS, OWNER)
    kube.namespace_objects[ns]["metadata"]["annotations"][PREFIX + "owner"] = OTHER
    with pytest.raises(Exception) as exc:
        store.create(OWNER).reference
    assert exc.value.status_code == 409
    assert len(kube.items) == 1


def test_baseline_drift_blocks_new_sandbox_instead_of_loosening_policy(setup):
    _, store, kube, _ = setup
    store.create(OWNER).reference
    ns = namespace_name(SETTINGS, OWNER)
    kube.baseline[("NetworkPolicy", ns, "sandbox-isolation")]["spec"]["ingress"] = [{}]
    with pytest.raises(Exception) as exc:
        store.create(OWNER).reference
    assert exc.value.status_code == 409
    assert len(kube.items) == 1


def test_suspending_one_sandbox_does_not_suspend_others(setup):
    browser, store, kube, _ = setup
    a, b = store.create(OWNER).reference, store.create(OWNER).reference
    browser.post(BASE + f"/sandboxes/{a['metadata']['name']}/suspend", headers=HEADERS)
    assert (
        kube.items[(a["metadata"]["namespace"], a["metadata"]["name"])]["spec"][
            "operatingMode"
        ]
        == "Suspended"
    )
    assert (
        kube.items[(b["metadata"]["namespace"], b["metadata"]["name"])]["spec"][
            "operatingMode"
        ]
        == "Running"
    )


@pytest.mark.parametrize("title", ["", "   ", "a" * 81, "bad\nname"])
def test_invalid_sandbox_title_rejected(setup, title):
    browser, _, kube, _ = setup
    assert (
        browser.post(
            BASE + "/sandboxes", headers=HEADERS, json={"title": title}
        ).status_code
        == 422
    )
    assert not kube.items


def test_new_user_inventory_does_not_create_a_namespace(setup):
    browser, _, kube, _ = setup
    assert browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"] == []
    assert not kube.namespace_objects


def test_narrowed_policy_selector_cannot_leave_new_pods_unprotected(setup):
    _, store, kube, _ = setup
    store.create(OWNER).reference
    ns = namespace_name(SETTINGS, OWNER)
    kube.baseline[("NetworkPolicy", ns, "sandbox-isolation")]["spec"]["podSelector"] = {
        "matchLabels": {"unrelated": "app"}
    }
    with pytest.raises(Exception) as exc:
        store.create(OWNER).reference
    assert exc.value.status_code == 409


def test_deleting_one_sandbox_retains_namespace_and_other_sandbox(setup):
    browser, store, kube, _ = setup
    a, b = store.create(OWNER).reference, store.create(OWNER).reference
    assert (
        browser.delete(
            BASE + f"/sandboxes/{a['metadata']['name']}", headers=HEADERS
        ).status_code
        == 202
    )
    assert list(kube.items) == [(b["metadata"]["namespace"], b["metadata"]["name"])]
    assert namespace_name(SETTINGS, OWNER) in kube.namespace_objects


def test_platform_can_configure_per_user_quota_and_extra_egress(setup):
    from dataclasses import replace

    _, _, kube, _ = setup
    policy = {
        "podSecurityVersion": "v1.34",
        "baselineNetworkPolicy": True,
        "publicHttpsEgress": False,
        "quota": {"requests.cpu": "12", "requests.storage": "200Gi"},
        "extraEgress": [
            {
                "to": [{"ipBlock": {"cidr": "203.0.113.0/24"}}],
                "ports": [{"protocol": "TCP", "port": 443}],
            }
        ],
    }
    settings = replace(SETTINGS, namespace_policy=json.dumps(policy))
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    store.create(OWNER).reference
    ns = namespace_name(settings, OWNER)
    assert (
        kube.baseline[("ResourceQuota", ns, "sandbox-budget")]["spec"]["hard"]
        == policy["quota"]
    )
    assert (
        kube.baseline[("NetworkPolicy", ns, "sandbox-isolation")]["spec"]["egress"][1:]
        == policy["extraEgress"]
    )


def test_identical_request_ids_in_other_namespaces_cannot_cross_owners(setup):
    browser, store, _, _ = setup
    request_id = uuid4()
    a, b = (
        store.create(OWNER, "Project", request_id).reference,
        store.create(OTHER, "Project", request_id).reference,
    )
    assert a["metadata"]["name"] == b["metadata"]["name"]
    assert a["metadata"]["namespace"] != b["metadata"]["namespace"]
    assert (
        a["metadata"]["annotations"][PREFIX + "owner"]
        != b["metadata"]["annotations"][PREFIX + "owner"]
    )
    rows = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"]
    assert len(rows) == 1 and rows[0]["owner"] == OWNER


SMALL = {
    "cpu_request_millicores": 250,
    "cpu_limit_millicores": 1000,
    "memory_request_mib": 512,
    "memory_limit_mib": 2048,
    "workspace_gib": 10,
}
LARGE = {
    "cpu_request_millicores": 1000,
    "cpu_limit_millicores": 3000,
    "memory_request_mib": 2048,
    "memory_limit_mib": 8192,
    "workspace_gib": 50,
}


def suspended(kube, cr):
    record = kube.items[(cr["metadata"]["namespace"], cr["metadata"]["name"])]
    record["spec"]["operatingMode"] = "Suspended"
    record["status"] = {
        "conditions": [
            {
                "type": "Suspended",
                "status": "True",
                "observedGeneration": record["metadata"]["generation"],
            }
        ]
    }


def test_each_sandbox_persists_and_exposes_its_selected_allocation(setup):
    browser, _, kube, _ = setup
    for size in (SMALL, LARGE):
        response = browser.post(
            BASE + "/sandboxes", headers=HEADERS, json={"resources": size}
        )
        assert response.status_code == 201
        row = response.json()
        assert row["allocation"] == size
        cr = kube.items[(row["namespace"], row["id"])]
        assert (
            cr["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"][
                "storage"
            ]
            == f"{size['workspace_gib']}Gi"
        )
        assert (
            cr["spec"]["podTemplate"]["spec"]["containers"][0]["resources"]["limits"][
                "cpu"
            ]
            == f"{size['cpu_limit_millicores']}m"
        )
    listing = browser.get(BASE + "/sandboxes", headers=HEADERS).json()
    assert sorted(
        (s["allocation"] for s in listing["sandboxes"]),
        key=lambda a: a["workspace_gib"],
    ) == [SMALL, LARGE]
    assert listing["resource_policy"] == DEFAULT_POLICY


@pytest.mark.parametrize(
    "change",
    [
        {"cpu_limit_millicores": 4001},
        {"cpu_request_millicores": 1001},
        {"memory_limit_mib": 8193},
        {"memory_request_mib": 2049},
        {"workspace_gib": 201},
        {"workspace_gib": 0},
        {"workspace_gib": 5.5},
        {"cpu_limit_millicores": "1000"},
        {"cpu_request_millicores": True},
        {"runtimeClassName": "runc"},
    ],
)
def test_invalid_resource_selection_cannot_create_cr_or_namespace(setup, change):
    browser, _, kube, _ = setup
    response = browser.post(
        BASE + "/sandboxes", headers=HEADERS, json={"resources": {**SMALL, **change}}
    )
    assert response.status_code == 422
    assert not kube.items and not kube.namespace_objects


def test_retry_cannot_reuse_request_id_for_different_resources(setup):
    browser, _, kube, _ = setup
    body = {"request_id": str(uuid4()), "resources": SMALL}
    assert (
        browser.post(BASE + "/sandboxes", headers=HEADERS, json=body).status_code == 201
    )
    assert (
        browser.post(
            BASE + "/sandboxes", headers=HEADERS, json={**body, "resources": LARGE}
        ).status_code
        == 409
    )
    assert len(kube.items) == 1


def test_cpu_memory_edit_after_suspend_preserves_workspace_credentials_and_identity(
    setup,
):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    suspended(kube, cr)
    record = kube.items[(cr["metadata"]["namespace"], cr["metadata"]["name"])]
    record["spec"]["podTemplate"]["spec"]["containers"][0]["resources"]["limits"][
        "ephemeral-storage"
    ] = "9Gi"
    updated = {**SMALL, "workspace_gib": 20}
    name, ns = cr["metadata"]["name"], cr["metadata"]["namespace"]
    response = browser.put(
        BASE + f"/sandboxes/{name}/resources", headers=HEADERS, json=updated
    )
    assert response.status_code == 200 and response.json()["allocation"] == updated
    result = kube.items[(ns, name)]
    assert result["metadata"]["annotations"] == cr["metadata"]["annotations"]
    assert result["spec"]["volumeClaimTemplates"] == cr["spec"]["volumeClaimTemplates"]
    assert result["spec"]["podTemplate"]["spec"].get("volumes", []) == cr["spec"][
        "podTemplate"
    ]["spec"].get("volumes", [])
    assert result["spec"]["operatingMode"] == "Suspended"
    assert (
        result["spec"]["podTemplate"]["spec"]["containers"][0]["resources"]["limits"][
            "ephemeral-storage"
        ]
        == "9Gi"
    )
    assert (
        result["spec"]["podTemplate"]["spec"]["containers"][0]["env"]
        == cr["spec"]["podTemplate"]["spec"]["containers"][0]["env"]
    )
    assert (
        browser.put(
            BASE + f"/sandboxes/{name}/resources", headers=HEADERS, json=updated
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    "mode", ["Running", "Suspending", "Stale suspended", "Pod terminating"]
)
def test_resource_edit_requires_confirmed_suspension_and_no_existing_pod(setup, mode):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    name, ns = cr["metadata"]["name"], cr["metadata"]["namespace"]
    if mode != "Running":
        suspended(kube, cr)
        if mode == "Suspending":
            kube.items[(ns, name)]["status"] = {}
        elif mode == "Stale suspended":
            kube.items[(ns, name)]["metadata"]["generation"] += 1
        elif mode == "Pod terminating":
            kube.read_namespaced_pod = Mock(return_value=SimpleNamespace())
    response = browser.put(
        BASE + f"/sandboxes/{name}/resources",
        headers=HEADERS,
        json={**SMALL, "workspace_gib": 20},
    )
    assert response.status_code == 409
    assert kube.items[(ns, name)]["spec"]["podTemplate"] == cr["spec"]["podTemplate"]


def test_existing_workspace_resize_is_explicitly_rejected(setup):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    suspended(kube, cr)
    response = browser.put(
        BASE + f"/sandboxes/{cr['metadata']['name']}/resources",
        headers=HEADERS,
        json=SMALL,
    )
    assert response.status_code == 409 and "immutable" in response.json()["detail"]


def test_another_user_cannot_resize_sandbox(setup):
    browser, store, kube, _ = setup
    cr = store.create(OTHER).reference
    suspended(kube, cr)
    response = browser.put(
        BASE + f"/sandboxes/{cr['metadata']['name']}/resources",
        headers=HEADERS,
        json={**SMALL, "workspace_gib": 20},
    )
    assert response.status_code == 404


def test_operator_defaults_and_bounds_apply_when_creation_omits_resources():
    from dataclasses import replace

    kube, upstream = Kubernetes(), Omnigent()
    limits = {
        **DEFAULT_POLICY,
        "defaults": SMALL,
        "cpu_millicores": {"min": 100, "max": 1500},
    }
    settings = replace(SETTINGS, resource_policy=json.dumps(limits))
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    with TestClient(create_app(settings, store, upstream)) as browser:
        assert (
            browser.post(BASE + "/sandboxes", headers=HEADERS).json()["allocation"]
            == SMALL
        )
        assert (
            browser.post(
                BASE + "/sandboxes", headers=HEADERS, json={"resources": LARGE}
            ).status_code
            == 422
        )


def test_quantity_display_reads_cr_values_without_portal_metadata():
    cr = manifest(SETTINGS, OWNER)
    resources = cr["spec"]["podTemplate"]["spec"]["containers"][0]["resources"]
    resources["limits"]["cpu"] = "2"
    resources["limits"]["memory"] = "4Gi"
    assert view(cr)["allocation"] == DEFAULT_POLICY["defaults"]


def test_resource_editor_rejects_cross_origin_requests(setup):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    suspended(kube, cr)
    assert (
        browser.put(
            BASE + f"/sandboxes/{cr['metadata']['name']}/resources",
            headers={**HEADERS, "Origin": "https://attacker.example"},
            json={**SMALL, "workspace_gib": 20},
        ).status_code
        == 403
    )


def test_compute_edits_are_applied_to_the_template_used_on_resume(setup):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    suspended(kube, cr)
    name, ns = cr["metadata"]["name"], cr["metadata"]["namespace"]
    new = {**LARGE, "workspace_gib": 20}
    assert (
        browser.put(
            BASE + f"/sandboxes/{name}/resources", headers=HEADERS, json=new
        ).status_code
        == 200
    )
    response = browser.post(BASE + f"/sandboxes/{name}/resume", headers=HEADERS)
    assert response.status_code == 200 and response.json()["allocation"] == new
    assert kube.items[(ns, name)]["spec"]["operatingMode"] == "Running"


def test_runner_resume_keeps_retained_native_configuration(setup):
    browser, store, kube, _ = setup
    cr = store.create(OWNER).reference
    name = cr["metadata"]["name"]
    before = deepcopy(cr["spec"]["podTemplate"])
    from dataclasses import replace

    definitions = json.loads(SETTINGS.profiles)
    definitions[0]["agentSandbox"]["spec"]["podTemplate"]["spec"]["containers"][0][
        "image"
    ] = "new-image"
    store.settings = replace(SETTINGS, profiles=json.dumps(definitions))
    browser.post(BASE + f"/sandboxes/{name}/suspend", headers=HEADERS)
    assert (
        browser.post(BASE + f"/sandboxes/{name}/resume", headers=HEADERS).status_code
        == 200
    )
    assert (
        kube.items[(cr["metadata"]["namespace"], name)]["spec"]["podTemplate"] == before
    )


def test_configured_egress_changes_reconcile_existing_user_namespace(setup):
    from dataclasses import replace

    _, store, kube, _ = setup
    store.create(OWNER).reference
    extra = [
        {
            "to": [{"ipBlock": {"cidr": "203.0.113.0/24"}}],
            "ports": [{"protocol": "TCP", "port": 443}],
        }
    ]
    policy = json.loads(SETTINGS.namespace_policy)
    policy["extraEgress"] = extra
    settings = replace(SETTINGS, namespace_policy=json.dumps(policy))
    UserNamespaces(settings, kube, kube, kube).ensure(OWNER)
    network = kube.baseline[
        ("NetworkPolicy", namespace_name(settings, OWNER), "sandbox-isolation")
    ]["spec"]
    assert network["egress"][-1:] == extra
    assert network["ingress"] == [] and network["podSelector"] == {}
    UserNamespaces(SETTINGS, kube, kube, kube).ensure(OWNER)
    assert len(network["egress"]) == 2


def test_profile_environment_is_retained_after_catalog_changes():
    from dataclasses import replace

    definitions = json.loads(SETTINGS.profiles)
    host = definitions[0]["agentSandbox"]["spec"]["podTemplate"]["spec"]["containers"][
        0
    ]
    host["env"].extend(
        {"name": name, "value": "https://first.example.com"}
        for name in ("CAIPE_SERVER_URL", "CAIPE_AUTH_URL")
    )
    settings = replace(SETTINGS, profiles=json.dumps(definitions))
    kube = Kubernetes()
    store = Store(
        settings,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(settings, kube, kube, kube),
        metadata=kube.metadata,
    )
    first = store.create(OWNER).reference
    name = first["metadata"]["name"]
    store.mode(name, OWNER, "Suspended").reference
    for entry in host["env"]:
        if entry["name"].startswith("CAIPE_"):
            entry["value"] = "https://second.example.com"
    changed = replace(settings, profiles=json.dumps(definitions))
    store = Store(
        changed,
        custom=kube,
        core=kube,
        namespaces=UserNamespaces(changed, kube, kube, kube),
        metadata=kube.metadata,
    )
    resumed = store.mode(name, OWNER, "Running").reference
    second = store.create(OWNER).reference
    for cr, expected in [
        (resumed, "https://first.example.com"),
        (second, "https://second.example.com"),
    ]:
        assert [
            e["value"]
            for e in cr["spec"]["podTemplate"]["spec"]["containers"][0]["env"]
            if e["name"].startswith("CAIPE_")
        ] == [expected, expected]
