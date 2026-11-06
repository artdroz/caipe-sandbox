"""Bind Kubernetes exec to a verified Agent Sandbox Pod."""

import json
import logging

from fastapi import HTTPException
from kubernetes import client
from kubernetes.stream import stream
from kubernetes.stream.ws_client import ERROR_CHANNEL

from ...execution import ExecutionTarget


class Execution:
    def __init__(self, connection):
        self.connection = connection
        self.status = {}

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def _read_status(self):
        status = self.connection.read_channel(ERROR_CHANNEL)
        if status:
            self.status = json.loads(status)

    def read_all(self):
        # WSClient.read_all() clears the exit-status channel along with output.
        self._read_status()
        return self.connection.read_all()

    @property
    def returncode(self):
        if self.connection.is_open():
            return None
        self._read_status()
        if self.status.get("status") == "Success":
            return 0
        for cause in self.status.get("details", {}).get("causes", []):
            if cause.get("reason") == "ExitCode":
                return int(cause["message"])
        return None


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
                connection = stream(
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
                return Execution(connection)
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
