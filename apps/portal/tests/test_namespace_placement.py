import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_portal import BASE, HEADERS, OWNER, SETTINGS, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.config import Settings
from portal.namespaces import PREFIX, namespace_config


def test_default_is_one_namespace_per_sandbox():
    assert namespace_config(Settings()).strategy == "perSandbox"
    assert namespace_config(Settings()).choices == ["perSandbox", "perUser"]


@pytest.mark.parametrize(
    "config",
    [
        {"strategy": "perSandbox", "allowedStrategies": []},
        {"strategy": "perSandbox", "allowedStrategies": ["perUser"]},
        {"strategy": "perUser", "allowedStrategies": ["perUser", "perUser"]},
        {"strategy": "perUser", "allowedStrategies": ["anything"]},
    ],
)
def test_admin_choices_are_validated(config):
    with pytest.raises(ValueError):
        namespace_config(replace(SETTINGS, namespace=json.dumps(config)))


def test_create_choices_are_enforced_saved_and_retry_safe():
    settings = replace(
        SETTINGS,
        namespace=json.dumps(
            {"strategy": "perSandbox", "allowedStrategies": ["perSandbox", "perUser"]}
        ),
    )
    store, kube = store_for(settings)
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        catalog = browser.get(BASE + "/sandboxes", headers=HEADERS).json()
        assert catalog["namespace_strategy"] == "perSandbox"
        assert catalog["namespace_choices"] == ["perSandbox", "perUser"]
        request = {"request_id": str(uuid4()), "namespace_strategy": "perUser"}
        first = browser.post(BASE + "/sandboxes", headers=HEADERS, json=request)
        assert first.status_code == 201
        first = first.json()
        sibling = browser.post(
            BASE + "/sandboxes", headers=HEADERS, json={"namespace_strategy": "perUser"}
        ).json()
        separate = browser.post(BASE + "/sandboxes", headers=HEADERS, json={}).json()
        assert first["namespace"] == sibling["namespace"] != separate["namespace"]
        assert first["namespace_strategy"] == "perUser"
        assert separate["namespace_strategy"] == "perSandbox"
        assert (
            kube.namespace_objects[first["namespace"]]["metadata"]["labels"][
                PREFIX + "namespace-strategy"
            ]
            == "perUser"
        )
        assert (
            browser.post(BASE + "/sandboxes", headers=HEADERS, json=request).json()[
                "id"
            ]
            == first["id"]
        )
        assert (
            browser.post(
                BASE + "/sandboxes",
                headers=HEADERS,
                json={**request, "namespace_strategy": "perSandbox"},
            ).status_code
            == 409
        )
        assert (
            browser.post(
                BASE + "/sandboxes",
                headers=HEADERS,
                json={"namespace_strategy": "other"},
            ).status_code
            == 422
        )
        assert (
            browser.post(
                BASE + "/sandboxes", headers=HEADERS, json={"namespace": "arbitrary"}
            ).status_code
            == 422
        )
    changed, _ = store_for(
        replace(settings, namespace='{"strategy":"perSandbox"}'), kube
    )
    assert (
        changed.create(
            OWNER, request_id=request["request_id"], namespace_strategy="perUser"
        ).name
        == first["id"]
    )
    with pytest.raises(HTTPException, match="not allowed"):
        changed.create(OWNER, namespace_strategy="perUser")
    assert changed.mode(first["id"], OWNER, "Suspended").scope == first["namespace"]
    assert changed.mode(first["id"], OWNER, "Running").scope == first["namespace"]


def test_api_rejects_an_unapproved_mode_without_creating_resources():
    settings = replace(SETTINGS, namespace='{"strategy":"perSandbox"}')
    store, kube = store_for(settings)
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        result = browser.post(
            BASE + "/sandboxes", headers=HEADERS, json={"namespace_strategy": "perUser"}
        )
        assert result.status_code == 422
        assert not kube.namespace_objects and not store.metadata.list_sandboxes()
