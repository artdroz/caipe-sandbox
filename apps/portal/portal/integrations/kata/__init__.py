"""Kata RuntimeClass presentation, independent of the workload lifecycle adapter."""

import time
from threading import Lock

from kubernetes import client
from kubernetes.client import ApiException
from urllib3.exceptions import HTTPError

from ..status import IntegrationStatus


class Status:
    def __init__(self, catalog):
        self.catalog = catalog
        self.cache = {}
        self.lock = Lock()

    def handler(self, name):
        with self.lock:
            cached = self.cache.get(name)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            api = getattr(self.catalog.core, "api_client", None)
            if api is None:
                return None
            try:
                value = client.NodeV1Api(api).read_runtime_class(
                    name, _request_timeout=3
                )
                handler = self.catalog.namespaces.data(value).get("handler", "")
            except (ApiException, HTTPError, OSError):
                handler = ""
            if len(self.cache) >= 64:
                self.cache.pop(next(iter(self.cache)))
            self.cache[name] = (time.monotonic() + 30, handler)
            return handler

    def status(self, sandbox):
        native = sandbox.reference
        if not isinstance(native, dict):
            return None
        name = (
            native.get("spec", {})
            .get("podTemplate", {})
            .get("spec", {})
            .get("runtimeClassName")
        )
        if not name:
            return None
        handler = self.handler(name)
        if not handler or not handler.startswith("kata"):
            return None
        return IntegrationStatus(
            id="kata",
            title="Kata",
            layer="Isolation",
            icon="cpu",
            state="configured",
            detail=f"RuntimeClass {name} selects {handler}. Runtime configuration; not a host attestation.",
        )
