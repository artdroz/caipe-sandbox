"""Operator links are bounded, safe browser URLs and available in both modes."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from test_caipe import CAIPE, headers
from test_oidc import OIDC
from test_portal import SETTINGS, Omnigent
from test_profiles import store_for

from portal.app import create_app
from portal.config import Settings, header_links


def test_default_docs_link_and_disabled_links():
    assert header_links(Settings()) == [
        {"title": "Docs", "url": "https://upgraded-adventure-w96874e.pages.github.io/"}
    ]
    assert header_links(replace(SETTINGS, header_links="[]")) == []


@pytest.mark.parametrize("settings", [SETTINGS, OIDC, CAIPE])
def test_custom_links_reach_standalone_and_hosted_browser_config(settings):
    links = [
        {"title": name, "url": f"https://example.com/{name.lower()}"}
        for name in ("Docs", "Support", "Status")
    ]
    settings = replace(settings, header_links=json.dumps(links))
    store, _ = store_for(settings)
    with TestClient(create_app(settings, store, Omnigent())) as browser:
        response = browser.get(
            settings.base_path + "/auth/config",
            headers=headers() if settings.auth_mode == "caipe" else {},
        )
        assert response.status_code == 200
        assert response.json()["header_links"] == links


@pytest.mark.parametrize(
    "links",
    [
        [{"title": "Docs", "url": "https://example.com"}] * 4,
        [{"title": "Docs", "url": "javascript:alert(1)"}],
        [{"title": "Docs", "url": "data:text/html,test"}],
        [{"title": "Docs", "url": "/relative/path"}],
        [{"title": " ", "url": "https://example.com"}],
        [{"title": "a" * 41, "url": "https://example.com"}],
        [{"title": "Docs"}],
        {"title": "Docs", "url": "https://example.com"},
    ],
)
def test_invalid_link_configuration_fails_at_startup(monkeypatch, links):
    for name, value in SETTINGS.__dict__.items():
        monkeypatch.setenv("PORTAL_" + name.upper(), str(value))
    monkeypatch.setenv("PORTAL_HEADER_LINKS", json.dumps(links))
    with pytest.raises(ValueError):
        Settings.from_env()
