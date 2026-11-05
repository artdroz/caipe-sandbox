import json
import subprocess
from dataclasses import replace
from unittest.mock import Mock

import pytest
from execution_fakes import target as execution_target
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, SETTINGS, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.profiles import Helper
from portal.tools import ToolStatus, probe_command, probe_state

CUSTOM = {
    "id": "example",
    "title": "Example CLI",
    "script": "exec example auth login --label 'a; echo unsafe'",
    "status": {"command": ["example", "auth", "status"], "json_field": "auth.ready"},
}


def probe(tmp_path, definition, output, exit_code=0):
    cli = tmp_path / "example"
    cli.write_text(
        "#!/bin/sh\nprintf '%s' '" + output + "'\nexit " + str(exit_code) + "\n"
    )
    cli.chmod(0o700)
    config = Helper.model_validate(definition).status
    if config is None:
        return {definition["id"]: "unknown"}
    response = subprocess.run(
        probe_command(config),
        env={"PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        definition["id"]: probe_state(
            config, response.stdout, response.stderr, response.returncode
        )
    }


def test_configured_helper_is_published_and_probed_without_builtin_names(tmp_path):
    profiles = json.loads(SETTINGS.profiles)
    profiles[0]["helpers"] = [CUSTOM]
    settings = replace(SETTINGS, profiles=json.dumps(profiles))
    store, _ = store_for(settings)
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        assert browser.get(BASE + "/sandboxes").status_code == 401
        data = browser.get(BASE + "/sandboxes", headers=HEADERS).json()
        assert "harnesses" not in data
        assert data["profiles"][0]["helpers"] == [
            {
                "id": "example",
                "title": "Example CLI",
                "icon": "terminal",
                "status_available": True,
            }
        ]
    response = probe(tmp_path, CUSTOM, '{"auth":{"ready":true},"token":"secret"}')
    assert response == {"example": "signed-in"}
    assert "secret" not in json.dumps(response)


@pytest.mark.parametrize(
    "output,exit_code,expected",
    [
        ('{"auth":{"ready":false}}', 0, "sign-in"),
        ('{"auth":{"ready":"true"}}', 0, "unknown"),
        ("not json", 1, "unknown"),
    ],
)
def test_custom_json_probe_fails_closed(tmp_path, output, exit_code, expected):
    assert probe(tmp_path, CUSTOM, output, exit_code) == {"example": expected}


def test_exit_code_probe_and_helper_without_probe(tmp_path):
    definition = {
        **CUSTOM,
        "status": {"command": ["example"], "signed_out_exit_codes": [4]},
    }
    assert probe(tmp_path, definition, "", 4) == {"example": "sign-in"}
    assert probe(tmp_path, {**CUSTOM, "status": None}, "") == {"example": "unknown"}


def test_probe_arguments_are_literal_without_python_on_path(tmp_path):
    cli = tmp_path / "example tool"
    cli.write_text('#!/bin/sh\nprintf "%s" "$1"\n')
    cli.chmod(0o700)
    marker = tmp_path / "injected"
    argument = f"a; touch {marker}; $(touch {marker}) `touch {marker}`"
    helper = Helper.model_validate(
        {
            **CUSTOM,
            "status": {"command": [str(cli), argument]},
        }
    )
    response = subprocess.run(
        probe_command(helper.status),
        env={"PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    assert response.stdout == argument
    assert not marker.exists()
    assert (
        probe_state(
            helper.status, response.stdout, response.stderr, response.returncode
        )
        == "signed-in"
    )


def test_command_exit_127_is_not_mistaken_for_a_missing_executable(tmp_path):
    definition = {
        **CUSTOM,
        "status": {"command": ["example"], "signed_out_exit_codes": [127]},
    }
    assert probe(tmp_path, definition, "missing dependency", 127) == {
        "example": "sign-in"
    }


@pytest.mark.parametrize(
    "change",
    [
        {"script": ""},
        {"id": "bad/name"},
        {"status": {"command": [""]}},
        {"status": {"command": ["example\nwhoami"]}},
        {"status": {"command": ["example"], "signed_out_exit_codes": [0]}},
        {"status": {"command": ["example"], "signed_out_contains": [""]}},
        {"typo": True},
    ],
)
def test_invalid_helper_configuration_prevents_startup(change):
    profiles = json.loads(SETTINGS.profiles)
    profiles[0]["helpers"] = [{**CUSTOM, **change}]
    with pytest.raises(ValueError):
        create_app(replace(SETTINGS, profiles=json.dumps(profiles)))


def test_empty_helper_list_never_executes_status_probe(monkeypatch):

    stream = Mock()
    pod = execution_target(stream)
    assert ToolStatus().status(pod) == {}
    stream.assert_not_called()
