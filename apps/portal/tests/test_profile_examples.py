import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, OWNER, SETTINGS, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.integrations.agent_sandbox.inventory import manifest, resolve
from portal.profiles import Profile, Profiles

APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "filename",
    [
        "profiles.values.yaml",
        "omnigent.values.yaml",
        "caipe.values.yaml",
        "engineering.values.yaml",
    ],
)
def test_example_profiles_are_complete_and_consumer_configuration_stays_in_them(
    filename,
):
    values = yaml.safe_load((APP / "examples" / filename).read_text())
    settings = replace(
        SETTINGS,
        profiles=json.dumps(values["profiles"]),
        default_profile=values["defaultProfile"],
    )
    profiles = Profiles(settings)
    for definition in profiles.items.values():
        cr, snapshot = resolve(settings, OWNER, profile=definition, catalog=profiles)
        pod = cr["spec"]["podTemplate"]["spec"]
        supplied = definition.agentSandbox.spec["podTemplate"]["spec"]
        host = pod["containers"][0]
        assert host["command"] == supplied["containers"][0]["command"]
        assert host["env"] == supplied["containers"][0].get("env", [])
        assert pod.get("volumes", []) == supplied.get("volumes", [])
        assert not any(
            key.endswith("/host-id") for key in cr["metadata"]["annotations"]
        )
        assert "omnigent" not in snapshot["definition"]


def test_native_configmap_and_secret_file_references_are_preserved():
    definitions = json.loads(SETTINGS.profiles)
    pod = definitions[0]["agentSandbox"]["spec"]["podTemplate"]["spec"]
    pod["volumes"] = [
        {"name": "config", "configMap": {"name": "operator-files"}},
        {"name": "credentials", "secret": {"secretName": "operator-credentials"}},
    ]
    host = pod["containers"][0]
    host["volumeMounts"] += [
        {"name": "config", "mountPath": "/etc/tool", "readOnly": True},
        {"name": "credentials", "mountPath": "/var/run/tool", "readOnly": True},
    ]
    host["env"] += [
        {"name": "TOOL_URL", "value": "https://consumer.example.com"},
        {
            "name": "TOOL_TOKEN",
            "valueFrom": {
                "secretKeyRef": {"name": "operator-credentials", "key": "token"}
            },
        },
    ]
    settings = replace(SETTINGS, profiles=json.dumps(definitions))
    rendered = manifest(settings, OWNER)["spec"]["podTemplate"]["spec"]
    assert rendered["volumes"] == pod["volumes"]
    assert rendered["containers"][0]["env"] == host["env"]
    assert rendered["containers"][0]["volumeMounts"] == host["volumeMounts"]


def test_portal_no_longer_exchanges_consumer_credentials_or_reads_host_inventory():
    upstream = Omnigent()
    original = upstream.get

    async def get(path, **kwargs):
        assert path == "/v1/me"
        return await original(path, **kwargs)

    upstream.get = get
    upstream.post = Mock(
        side_effect=AssertionError("Consumer login belongs to its profile")
    )
    store, kube = store_for()
    with TestClient(create_app(SETTINGS, store, upstream)) as browser:
        created = browser.post(BASE + "/sandboxes", headers=HEADERS, json={}).json()
        for path in ["connect", "connect/complete"]:
            assert (
                browser.post(
                    BASE + f"/sandboxes/{created['id']}/{path}", headers=HEADERS
                ).status_code
                == 404
            )
        row = browser.get(BASE + "/sandboxes", headers=HEADERS).json()["sandboxes"][0]
        assert "host_status" not in row and "host_id" not in row
        assert not kube.secrets
    upstream.post.assert_not_called()


@pytest.mark.parametrize("command", [[], [""], ["bash\nwhoami"]])
def test_invalid_terminal_commands_are_rejected(command):
    definition = json.loads(SETTINGS.profiles)[0]
    definition["terminal"] = {"command": command}
    with pytest.raises(ValueError):
        Profile.model_validate(definition)


@pytest.mark.parametrize("value", [None, [], {}])
def test_profile_catalog_has_no_generated_fallback(value):
    with pytest.raises(ValueError, match="Profiles must contain"):
        Profiles(replace(SETTINGS, profiles=json.dumps(value)))


def test_omnigent_profile_startup_waits_for_cli_login_and_preserves_tokens(tmp_path):
    executable = tmp_path / "omnigent"
    executable.write_text('#!/bin/sh\ntouch "$HOME/host-started"\nsleep 20\n')
    executable.chmod(0o700)
    server = "https://omnigent.example.com"
    process = subprocess.Popen(
        [sys.executable, str(APP.parents[1] / "sandbox-images/common-tools/sandbox/integrations/omnigent/main.py")],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "OMNIGENT_SERVER_URL": server,
            "PATH": str(tmp_path) + ":" + os.environ["PATH"],
        },
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert "Waiting for Omnigent login" in process.stdout.readline()
        assert not (tmp_path / "host-started").exists()
        tokens = tmp_path / ".omnigent/auth_tokens.json"
        tokens.parent.mkdir()
        record = {
            server: {
                "user_id": OWNER,
                "token": "refreshed",
                "refresh_token": "retained",
            }
        }
        tokens.write_text(json.dumps(record))
        deadline = time.monotonic() + 5
        while not (tmp_path / "host-started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "host-started").exists()
        assert json.loads(tokens.read_text()) == record
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=12)
        process.stdout.close()


def test_omnigent_profile_selects_image_service_without_inline_scripts():
    values = yaml.safe_load((APP / "examples/omnigent.values.yaml").read_text())
    definition = next(p for p in values["profiles"] if p["id"] == "omnigent")
    pod = definition["agentSandbox"]["spec"]["podTemplate"]["spec"]
    host = pod["containers"][0]
    assert host["command"] == ["sandbox-start"]
    assert host["args"] == ["--service", "omnigent"]
    assert "initContainers" not in pod
    assert "python3" not in host["command"]
