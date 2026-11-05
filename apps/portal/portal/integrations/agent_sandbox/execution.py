"""Bind Kubernetes exec to a verified Agent Sandbox Pod."""

import logging

from fastapi import HTTPException
from kubernetes import client
from kubernetes.stream import stream

from ...execution import ExecutionTarget


def target(resource, core, *, admin=False):
    metadata = resource["metadata"]
    pod = core.read_namespaced_pod(
        resource.get("status", {}).get("podName") or metadata["name"],
        metadata["namespace"],
    )
    if pod.status.phase != "Running" or not any(
        ref.uid == metadata["uid"] for ref in pod.metadata.owner_references or []
    ):
        raise HTTPException(409, "Sandbox terminal is not ready")
    name, namespace = pod.metadata.name, pod.metadata.namespace
    container = "host"
    if admin:
        containers = pod.spec.containers
        if not any(c.name == "host" for c in containers):
            container = containers[0].name

    def connector(command, *, stdin, tty, timeout):
        try:
            with client.ApiClient() as api:
                executor = client.CoreV1Api(api)
                return stream(
                    executor.connect_get_namespaced_pod_exec,
                    name,
                    namespace,
                    container=container,
                    command=command,
                    stdin=stdin,
                    stdout=True,
                    stderr=True,
                    tty=tty,
                    _preload_content=False,
                    _request_timeout=timeout,
                )
        except client.ApiException as exc:
            logging.getLogger(__name__).warning(
                "sandbox_exec_unavailable status=%s", exc.status
            )
            raise HTTPException(
                503, "Sandbox execution transport is unavailable"
            ) from None

    return ExecutionTarget(
        key=("agentSandbox", namespace, pod.metadata.uid),
        scope=namespace,
        sandbox_uid=metadata["uid"],
        connector=connector,
        default_command=("/bin/sh",) if admin and container != "host" else None,
    )
