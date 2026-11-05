from pathlib import Path

import pytest
from pydantic import ValidationError
from test_portal import BASE, HEADERS
from test_portal import setup as portal_setup

from portal.integrations.status import IntegrationStatus

setup = portal_setup


def test_badges_have_no_dependency_on_the_lifecycle_provider():
    runtime = IntegrationStatus(
        id="runtime", title="Custom runtime", layer="Runtime", state="active"
    )
    network = IntegrationStatus(
        id="egress",
        title="Egress",
        layer="Network",
        state="configured",
        image="egress.svg",
    )
    assert runtime.model_dump()["layer"] == "Runtime"
    assert network.model_dump()["image"] == "egress.svg"
    with pytest.raises(ValidationError):
        IntegrationStatus(
            id="egress", title="Egress", layer="Network", state="protected"
        )


@pytest.mark.parametrize(
    "image", ["../secret.svg", "https://example.com/logo.svg", "logo.txt"]
)
def test_badge_images_are_local_image_assets(image):
    with pytest.raises(ValidationError):
        IntegrationStatus(
            id="example",
            title="Example",
            layer="Workload",
            state="unknown",
            image=image,
        )


def test_integration_images_are_served_without_exposing_other_files(
    setup, tmp_path, monkeypatch
):
    from portal import app

    browser, _, _, _ = setup
    folder = tmp_path / "integrations"
    folder.mkdir()
    (folder / "example.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
    (folder / "private.txt").write_text("not an image")
    monkeypatch.setattr(app, "STATIC", Path(tmp_path))
    root = BASE.removesuffix("/api") + "/assets/integrations/"
    response = browser.get(root + "example.svg", headers=HEADERS)
    assert (
        response.status_code == 200
        and "image/svg+xml" in response.headers["content-type"]
    )
    for name in ["missing.svg", "private.txt", "..%2Fprivate.txt"]:
        assert browser.get(root + name, headers=HEADERS).status_code == 404


def test_kata_uses_the_runtime_handler_instead_of_guessing_from_the_class_name(
    monkeypatch,
):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from portal.integrations import kata

    reader = Mock(return_value={"handler": "kata-qemu-runtime-rs"})
    monkeypatch.setattr(
        kata.client, "NodeV1Api", lambda api: SimpleNamespace(read_runtime_class=reader)
    )
    catalog = SimpleNamespace(
        core=SimpleNamespace(api_client=object()),
        namespaces=SimpleNamespace(data=lambda value: value),
    )
    source = kata.Status(catalog)
    sandbox = SimpleNamespace(
        reference={
            "spec": {"podTemplate": {"spec": {"runtimeClassName": "engineering-vm"}}}
        }
    )
    badge = source.status(sandbox)
    assert badge.id == "kata" and badge.state == "configured"
    assert "engineering-vm" in badge.detail and "not a host attestation" in badge.detail
    source.status(sandbox)
    assert reader.call_count == 1
    reader.return_value = {"handler": "runc"}
    sandbox.reference["spec"]["podTemplate"]["spec"]["runtimeClassName"] = (
        "kata-sounding-name"
    )
    assert source.status(sandbox) is None
    assert source.status(SimpleNamespace(reference=None)) is None


def test_kata_lookup_failure_does_not_invent_an_isolation_badge(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from kubernetes.client import ApiException
    from portal.integrations import kata

    reader = Mock(side_effect=ApiException(status=403))
    monkeypatch.setattr(
        kata.client, "NodeV1Api", lambda api: SimpleNamespace(read_runtime_class=reader)
    )
    catalog = SimpleNamespace(
        core=SimpleNamespace(api_client=object()),
        namespaces=SimpleNamespace(data=lambda value: value),
    )
    source = kata.Status(catalog)
    sandbox = SimpleNamespace(
        reference={"spec": {"podTemplate": {"spec": {"runtimeClassName": "kata-dev"}}}}
    )
    assert source.status(sandbox) is None
    assert source.status(sandbox) is None
    assert reader.call_count == 1


@pytest.mark.parametrize("provider", ["agentSandbox", "openShell"])
@pytest.mark.parametrize(
    "command",
    [
        ["sandbox-start", "--service", "omnigent"],
        ["/usr/local/bin/sandbox-start", "--service=omnigent"],
    ],
)
def test_omnigent_reports_configured_service_without_claiming_host_health(
    provider, command
):
    from types import SimpleNamespace
    from portal.integrations.omnigent import Status

    spec = (
        {"command": command}
        if provider == "openShell"
        else {
            "podTemplate": {
                "spec": {"containers": [{"command": command[:1], "args": command[1:]}]}
            }
        }
    )
    manifest = {
        "apiVersion": "openshell.v1"
        if provider == "openShell"
        else "agents.x-k8s.io/v1beta1",
        "spec": spec,
    }
    sandbox = SimpleNamespace(
        record=SimpleNamespace(manifest=manifest), reference=manifest
    )
    badge = Status().status(sandbox)
    assert badge.id == "omnigent" and badge.state == "configured"
    assert "not checked" in badge.detail
    assert "SERVER_URL" not in badge.detail


def test_login_helper_or_a_random_command_does_not_claim_the_omnigent_service():
    from types import SimpleNamespace
    from portal.integrations.omnigent import Status

    for command in [
        ["echo", "--service", "omnigent"],
        ["sandbox-start", "--service", "other"],
    ]:
        manifest = {"apiVersion": "openshell.v1", "spec": {"command": command}}
        assert (
            Status().status(
                SimpleNamespace(
                    record=SimpleNamespace(manifest=manifest), reference=None
                )
            )
            is None
        )


def test_status_collection_preserves_backend_status_and_supports_future_sources():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from portal.integrations import Integrations
    from test_portal import OWNER
    from test_profiles import store_for

    store, _ = store_for()
    sandbox = store.create(OWNER)
    other = IntegrationStatus(
        id="future", title="Future integration", layer="Network", state="unknown"
    )
    store.integrations.status_sources = (
        SimpleNamespace(status=Mock(return_value=other)),
    )
    row = store.status_view(sandbox)
    assert [badge["id"] for badge in row["integrations"]] == ["future"]
    assert row["integrations"][0]["state"] == "unknown"
    existing = {"integrations": [{**other.model_dump(), "state": "active"}]}
    assert (
        Integrations.status(store.integrations, sandbox, existing)["integrations"][0][
            "state"
        ]
        == "active"
    )
