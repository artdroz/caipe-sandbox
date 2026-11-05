"""Portable chart installation, optional services and native operator objects."""

import subprocess
import tarfile
from pathlib import Path

import pytest
import yaml
from test_chart import CHART, render

pytestmark = pytest.importorskip("test_chart").pytestmark
DEFAULT_RUNTIME = {"runtimeClass": "", "allowedRuntimeClasses": [""]}


def objects(result):
    assert result.returncode == 0, result.stderr
    return [o for o in yaml.safe_load_all(result.stdout) if o]


def test_default_runtime_does_not_grant_unrestricted_runtimeclass_reads(tmp_path):
    resources = objects(render(tmp_path, DEFAULT_RUNTIME))
    bootstrap = next(
        o
        for o in resources
        if o["kind"] == "ClusterRole" and o["metadata"]["name"].endswith("-bootstrap")
    )
    assert not any("runtimeclasses" in r["resources"] for r in bootstrap["rules"])
    policy = next(
        o
        for o in resources
        if o["kind"] == "ValidatingAdmissionPolicy"
        and o["metadata"]["name"].endswith("-runners")
    )
    expression = policy["spec"]["validations"][0]["expression"]
    assert "!has(object.spec.runtimeClassName)" in expression
    assert "'' in [\"\"]" in expression


def test_portal_node_placement_does_not_leak_into_integration_controllers(tmp_path):
    placement = {
        "nodeSelector": {"kubernetes.io/arch": "amd64", "node-pool": "control"},
        "tolerations": [{"key": "control", "operator": "Exists"}],
        "affinity": {
            "podAntiAffinity": {"preferredDuringSchedulingIgnoredDuringExecution": []}
        },
    }
    resources = objects(
        render(tmp_path, DEFAULT_RUNTIME, agentSandbox={"enabled": True}, **placement)
    )
    pods = {
        c["name"]: o["spec"]["template"]["spec"]
        for o in resources
        if o["kind"] == "Deployment"
        for c in o["spec"]["template"]["spec"]["containers"]
    }
    assert all(pods["portal"][key] == value for key, value in placement.items())
    assert "nodeSelector" not in pods["agent-sandbox-controller"]
    assert "tolerations" not in pods["agent-sandbox-controller"]


def test_extra_objects_preserve_native_specs_and_explicit_namespaces(tmp_path):
    supplied = [
        {
            "apiVersion": "external-secrets.io/v1",
            "kind": "ExternalSecret",
            "metadata": {"name": "portal-auth", "namespace": "operators-choice"},
            "spec": {
                "secretStoreRef": {
                    "name": "company-vault",
                    "kind": "ClusterSecretStore",
                },
                "target": {"name": "portal-auth"},
                "data": [
                    {"secretKey": "client-secret", "remoteRef": {"key": "sandbox/oidc"}}
                ],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "literal-settings"},
            "data": {"literal": "{{ not_a_template }}", "count": "2"},
        },
    ]
    resources = objects(render(tmp_path, DEFAULT_RUNTIME, extraObjects=supplied))
    for expected in supplied:
        actual = next(
            o
            for o in resources
            if o["kind"] == expected["kind"]
            and o["metadata"]["name"] == expected["metadata"]["name"]
        )
        assert actual == expected


def test_optional_application_charts_render_only_when_selected(tmp_path):
    disabled = objects(render(tmp_path, DEFAULT_RUNTIME))
    assert {
        c["name"]
        for o in disabled
        if o["kind"] == "Deployment"
        for c in o["spec"]["template"]["spec"]["containers"]
    } == {"portal"}
    enabled = objects(
        render(
            tmp_path,
            DEFAULT_RUNTIME,
            agentSandbox={"enabled": True},
            omnigent={"enabled": True, "existingSecret": "omnigent-auth"},
        )
    )
    containers = {
        c["name"]: c
        for o in enabled
        if o["kind"] == "Deployment"
        for c in o["spec"]["template"]["spec"]["containers"]
    }
    assert set(containers) == {"portal", "agent-sandbox-controller", "omnigent"}
    assert containers["agent-sandbox-controller"]["image"].endswith(":v1.0.5")
    assert "5746692f3c3a9550" in containers["omnigent"]["image"]
    assert not any(o["kind"] == "DaemonSet" for o in enabled)
    assert not any(
        o["kind"].lower() in {"postgresql", "clustersecretstore", "ec2nodeclass"}
        for o in enabled
    )


def test_packaged_release_contains_optional_services_without_source_directories(
    tmp_path,
):
    values = {
        "agentSandbox": {"enabled": True},
        "openShell": {
            "enabled": True,
            "agentSandbox": {"preflight": {"enabled": False}},
            "server": {"credentialStorage": {"existingSecret": "gateway-key"}},
        },
        "omnigent": {"enabled": True, "existingSecret": "omnigent-auth"},
        "kata": {"enabled": True},
    }
    objects(render(tmp_path, DEFAULT_RUNTIME, **values))
    package = subprocess.run(
        ["helm", "package", str(CHART), "--destination", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert package.returncode == 0, package.stderr
    version = yaml.safe_load((CHART / "Chart.yaml").read_text())["version"]
    result = subprocess.run(
        [
            "helm",
            "template",
            "portable",
            str(tmp_path / f"caipe-sandbox-{version}.tgz"),
            "--kube-version",
            "1.34.0",
            "--include-crds",
            "-f",
            str(tmp_path / "values.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    resources = objects(result)
    assert any(
        o["kind"] == "CustomResourceDefinition"
        and o["metadata"]["name"] == "sandboxes.agents.x-k8s.io"
        for o in resources
    )
    containers = [
        c
        for o in resources
        if o["kind"] in {"Deployment", "StatefulSet", "DaemonSet"}
        for c in o["spec"]["template"]["spec"]["containers"]
    ]
    assert {"portal", "agent-sandbox-controller", "omnigent"} <= {
        c["name"] for c in containers
    }
    assert any("openshell" in c["image"] for c in containers)
    assert any("kata-deploy" in c["image"] for c in containers)


@pytest.mark.parametrize("name", ["agent-sandbox", "omnigent"])
def test_local_application_dependency_matches_its_repo_owned_source(name):
    source = CHART.parent / name
    metadata = yaml.safe_load((source / "Chart.yaml").read_text())
    with tarfile.open(
        CHART / "charts" / f"{name}-{metadata['version']}.tgz"
    ) as archive:
        for entry in archive.getmembers():
            if not entry.isfile():
                continue
            relative = Path(entry.name).relative_to(name)
            content = archive.extractfile(entry).read()
            if relative.name == "Chart.yaml":
                assert yaml.safe_load(content) == metadata
            else:
                assert content == (source / relative).read_bytes(), str(relative)
    dependencies = yaml.safe_load((CHART / "Chart.yaml").read_text())["dependencies"]
    assert all("sre-helm" not in d["repository"] for d in dependencies)
