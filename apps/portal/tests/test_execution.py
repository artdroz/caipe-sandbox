from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from execution_fakes import target as fake_target
from fastapi import HTTPException

from portal.execution import connect
from portal.integrations.agent_sandbox.execution import target


def test_provider_target_needs_no_kubernetes_object(monkeypatch):
    from portal.integrations.agent_sandbox import execution

    api = Mock(side_effect=AssertionError("Direct Kubernetes access is forbidden"))
    monkeypatch.setattr(execution.client, "ApiClient", api)
    stream = Mock()
    connector = Mock(return_value=stream)
    assert connect(fake_target(connector), ["sh"], tty=True, timeout=3) is stream
    connector.assert_called_once_with(["sh"], tty=True, stdin=True, timeout=3)
    api.assert_not_called()


def test_missing_or_failed_transport_has_no_native_fallback(monkeypatch):
    from portal.integrations.agent_sandbox import execution

    api = Mock()
    monkeypatch.setattr(execution.client, "ApiClient", api)
    with pytest.raises(HTTPException, match="execution transport is unavailable"):
        connect(SimpleNamespace(), ["sh"])
    with pytest.raises(HTTPException, match="provider unavailable"):
        connect(
            fake_target(Mock(side_effect=HTTPException(503, "provider unavailable"))),
            ["sh"],
        )
    api.assert_not_called()


def test_kubernetes_transport_keeps_verified_target_and_supported_exec_arguments(
    monkeypatch,
):
    from kubernetes.stream import ws_client

    resource = {
        "metadata": {"name": "sandbox", "namespace": "ns", "uid": "sandbox-uid"}
    }
    pod = SimpleNamespace(
        metadata=SimpleNamespace(
            name="sandbox",
            namespace="ns",
            uid="pod-uid",
            owner_references=[SimpleNamespace(uid="sandbox-uid")],
        ),
        status=SimpleNamespace(phase="Running"),
    )
    core = Mock(read_namespaced_pod=Mock(return_value=pod))
    resolved = target(resource, core)
    pod.metadata.name = "unrelated"
    stream = Mock()
    factory = Mock(return_value=stream)
    monkeypatch.setattr(ws_client, "WSClient", factory)
    assert connect(resolved, ["/bin/sh"], stdin=False) is stream
    assert factory.call_count == 1
    url = factory.call_args.args[1]
    assert "/namespaces/ns/pods/sandbox/exec?" in url
    assert "command=%2Fbin%2Fsh" in url and "container=host" in url
