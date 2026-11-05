"""Provision a user's namespace before granting the portal access to its contents."""

import hashlib
import json
import re
from typing import Literal

from fastapi import HTTPException
from kubernetes import client
from kubernetes.client import ApiException
from pydantic import BaseModel, ConfigDict, Field

from .integrations import namespace_backend, registered

APP = "agent-sandbox-portal"
PREFIX = "sandbox.caipe.io/"
LABEL = "app.kubernetes.io/name"


class NamespaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["perUser", "perSandbox"] = "perSandbox"
    allowedStrategies: list[Literal["perUser", "perSandbox"]] | None = Field(
        default=None, min_length=1, max_length=2
    )
    labels: dict[str, str] = Field(default_factory=dict, strict=True)
    annotations: dict[str, str] = Field(default_factory=dict, strict=True)

    @property
    def choices(self):
        return self.allowedStrategies or [self.strategy]

    def select(self, strategy=None):
        strategy = strategy or self.strategy
        if strategy not in self.choices:
            raise HTTPException(
                422, "Namespace placement is not allowed by platform policy"
            )
        return self.model_copy(update={"strategy": strategy})


def namespace_config(settings):
    value = NamespaceConfig.model_validate(json.loads(settings.namespace))
    if (
        len(set(value.choices)) != len(value.choices)
        or value.strategy not in value.choices
    ):
        raise ValueError(
            "Namespace choices must be unique and include the default strategy"
        )
    policy_labels = json.loads(settings.namespace_policy).get("labels", {})
    maps = {
        "labels": {**policy_labels, **value.labels},
        "annotations": value.annotations,
    }
    for kind, entries in maps.items():
        if len(entries) > 100:
            raise ValueError("Namespace metadata allows at most 100 entries per map")
        for key, item in entries.items():
            if not isinstance(key, str) or not isinstance(item, str):
                raise TypeError("Namespace labels and annotations must be string maps")
            parts = key.split("/")
            name = parts[-1]
            prefix = parts[0] if len(parts) == 2 else ""
            if (
                len(parts) > 2
                or not 1 <= len(name) <= 63
                or not re.fullmatch(r"[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?", name)
                or (
                    len(parts) == 2
                    and (
                        not prefix
                        or len(prefix) > 253
                        or any(
                            len(part) > 63
                            or not re.fullmatch(
                                r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?", part
                            )
                            for part in prefix.split(".")
                        )
                    )
                )
            ):
                raise ValueError(
                    "Namespace metadata contains an invalid Kubernetes key"
                )
            if key == LABEL or key.startswith(
                (
                    PREFIX,
                    "pod-security.kubernetes.io/",
                    "kubernetes.io/",
                    "k8s.io/",
                    *(prefix for p in registered() for prefix in p.reserved_prefixes),
                )
            ):
                raise ValueError(
                    f"Namespace metadata key is platform-controlled: {key}"
                )
            if kind == "labels" and (
                len(item) > 63
                or (
                    item
                    and not re.fullmatch(
                        r"[A-Za-z0-9](?:[-A-Za-z0-9_.]*[A-Za-z0-9])?", item
                    )
                )
            ):
                raise ValueError("Namespace label value is invalid")
    if (
        sum(len(k.encode()) + len(v.encode()) for k, v in value.annotations.items())
        > 16 * 1024
    ):
        raise ValueError("Namespace annotations exceed 16 KiB")
    quota = json.loads(settings.namespace_policy).get("quota", {})
    supported = {
        "requests.cpu",
        "limits.cpu",
        "requests.memory",
        "limits.memory",
        "requests.storage",
        "persistentvolumeclaims",
        "pods",
        "count/sandboxes.agents.x-k8s.io",
    }
    if "perSandbox" in value.choices and set(quota) - supported:
        raise ValueError(
            "perSandbox aggregate owner quota supports only CPU, memory, storage, PVC, Pod and Sandbox counts"
        )
    return value


def namespace_name(settings, owner, sandbox=None):
    if sandbox:
        digest = hashlib.sha256((owner + "/" + sandbox).encode()).hexdigest()[:32]
        return f"{settings.namespace_prefix}-sandbox-{digest}"
    slug = re.sub(r"[^a-z0-9]+", "-", owner.lower()).strip("-")[:32] or "user"
    digest = hashlib.sha256(owner.encode()).hexdigest()[:10]
    return f"{settings.namespace_prefix}-{slug}-{digest}"


def matches(expected, actual):
    if isinstance(expected, dict):
        if not expected:
            return isinstance(actual, dict) and not any(actual.values())
        return isinstance(actual, dict) and all(
            matches(value, actual.get(key)) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (actual is None and not expected) or (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(matches(a, b) for a, b in zip(expected, actual, strict=True))
        )
    return expected == actual


class UserNamespaces:
    def __init__(self, settings, core, networking=None, rbac=None):
        self.settings = settings
        self.core = core
        self.networking = networking or client.NetworkingV1Api()
        self.rbac = rbac or client.RbacAuthorizationV1Api()

    def for_owner(self, owner=None):
        names = []
        base = f"{LABEL}={APP},{PREFIX}instance={self.settings.namespace_access_role},{PREFIX}tenant=true"
        selectors = [base]
        if owner is not None:
            digest = hashlib.sha256(owner.encode()).hexdigest()[:32]
            selectors = [f"{base},{PREFIX}owner={digest}", f"{base},!{PREFIX}owner"]
        for selector in selectors:
            continuation = None
            while True:
                response = self.core.list_namespace(
                    label_selector=selector, limit=200, _continue=continuation
                )
                for item in response.items:
                    ns = self.data(item)
                    meta = ns["metadata"]
                    if not meta.get("deletionTimestamp") and (
                        owner is None
                        or meta.get("annotations", {}).get(PREFIX + "owner") == owner
                    ):
                        names.append(meta["name"])
                continuation = response.metadata._continue
                if not continuation:
                    break
        return names

    def get(self, owner, name=None):
        name = name or namespace_name(self.settings, owner)
        try:
            ns = self.core.read_namespace(name)
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise
        ns = self.data(ns)
        if (
            ns["metadata"].get("labels", {}).get(LABEL) != APP
            or ns["metadata"].get("labels", {}).get(PREFIX + "tenant") != "true"
            or ns["metadata"].get("annotations", {}).get(PREFIX + "owner") != owner
            or ns["metadata"].get("labels", {}).get(PREFIX + "instance")
            != self.settings.namespace_access_role
        ):
            raise HTTPException(
                409, "User namespace is unavailable or belongs to another owner"
            )
        if ns["metadata"].get("deletionTimestamp"):
            return None
        return name

    @staticmethod
    def data(value):
        with client.ApiClient() as api:
            return api.sanitize_for_serialization(value)

    def ensure_object(self, body, create, read, *args):
        try:
            create(*args, body)
        except ApiException as exc:
            if exc.status != 409:
                raise
            existing = self.data(read(body["metadata"]["name"], *args))
            if not matches(body, existing):
                raise HTTPException(
                    409,
                    "Namespace baseline differs from configured policy; platform reconciliation is required",
                ) from None

    def ensure_network(self, body, namespace):
        try:
            self.networking.create_namespaced_network_policy(namespace, body)
        except ApiException as exc:
            if exc.status != 409:
                raise
            existing = self.data(
                self.networking.read_namespaced_network_policy(
                    body["metadata"]["name"], namespace
                )
            )
            baseline = {
                **body,
                "spec": {k: v for k, v in body["spec"].items() if k != "egress"},
            }
            if not matches(baseline, existing):
                raise HTTPException(
                    409, "Namespace isolation differs from configured policy"
                ) from None
            if existing["spec"].get("egress", []) != body["spec"]["egress"]:
                self.networking.patch_namespaced_network_policy(
                    body["metadata"]["name"],
                    namespace,
                    {
                        "metadata": {
                            "resourceVersion": existing["metadata"].get(
                                "resourceVersion"
                            )
                        },
                        "spec": {"egress": body["spec"]["egress"]},
                    },
                )

    def ensure(
        self,
        owner,
        sandbox=None,
        namespace=None,
        backend="agentSandbox",
        strategy=None,
        expected_uid=None,
    ):
        settings = self.settings
        policy = json.loads(settings.namespace_policy)
        placement = namespace_config(settings)
        if strategy is not None:
            placement = NamespaceConfig.model_validate(
                {**placement.model_dump(), "strategy": strategy}
            )
        provider = namespace_backend(backend)
        name = namespace or (provider.namespace_name if provider else namespace_name)(
            settings, owner, sandbox if placement.strategy == "perSandbox" else None
        )
        previous = self.get(owner, name)
        if expected_uid and (
            not previous
            or self.data(self.core.read_namespace(name))["metadata"].get("uid")
            != expected_uid
        ):
            raise HTTPException(409, "Namespace changed; refresh and choose it again")
        if previous:
            existing_metadata = self.data(self.core.read_namespace(name))["metadata"]
            labels = existing_metadata.get("labels", {})
            annotations = existing_metadata.get("annotations", {})
        else:
            labels = {
                **policy.get("labels", {}),
                **placement.labels,
                PREFIX + "namespace-strategy": placement.strategy,
                PREFIX + "owner": hashlib.sha256(owner.encode()).hexdigest()[:32],
            }
            annotations = {
                **placement.annotations,
                **(
                    {PREFIX + "sandbox": sandbox}
                    if placement.strategy == "perSandbox"
                    else {}
                ),
            }
        ns = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": name,
                "labels": {
                    **labels,
                    **(
                        {
                            PREFIX + "backend": provider.key,
                            **provider.namespace_labels(settings),
                        }
                        if provider
                        else {}
                    ),
                    LABEL: APP,
                    PREFIX + "tenant": "true",
                    PREFIX + "instance": settings.namespace_access_role,
                    "pod-security.kubernetes.io/enforce": "restricted",
                    "pod-security.kubernetes.io/enforce-version": policy[
                        "podSecurityVersion"
                    ],
                },
                "annotations": {
                    **annotations,
                    PREFIX + "owner": owner,
                    PREFIX + "schema": "2",
                },
            },
        }
        self.ensure_object(ns, self.core.create_namespace, self.core.read_namespace)
        if self.get(owner, name) is None:
            raise HTTPException(
                409, "User namespace is being removed; retry when cleanup completes"
            )
        metadata = {"namespace": name, "labels": {LABEL: APP}}
        if provider:
            provider.bootstrap(self, name, metadata)
        else:
            sa = {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {**metadata, "name": settings.runner_service_account},
                "automountServiceAccountToken": False,
            }
            self.ensure_object(
                sa,
                self.core.create_namespaced_service_account,
                self.core.read_namespaced_service_account,
                name,
            )
            egress = [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "kube-system"
                                }
                            },
                            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                        }
                    ],
                    "ports": [
                        {"protocol": protocol, "port": 53}
                        for protocol in ("UDP", "TCP")
                    ],
                }
            ]
            if policy.get("publicHttpsEgress", True):
                egress.append(
                    {
                        "to": [
                            {
                                "ipBlock": {
                                    "cidr": "0.0.0.0/0",
                                    "except": [
                                        "10.0.0.0/8",
                                        "172.16.0.0/12",
                                        "192.168.0.0/16",
                                        "169.254.0.0/16",
                                        "127.0.0.0/8",
                                        "100.64.0.0/10",
                                    ],
                                }
                            }
                        ],
                        "ports": [{"protocol": "TCP", "port": 443}],
                    }
                )
            egress.extend(policy.get("extraEgress", []))
            network = {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {**metadata, "name": "sandbox-isolation"},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [],
                    "egress": egress,
                },
            }
            if policy.get("baselineNetworkPolicy", False):
                self.ensure_network(network, name)
        if policy.get("quota"):
            quota = {
                "apiVersion": "v1",
                "kind": "ResourceQuota",
                "metadata": {**metadata, "name": "sandbox-budget"},
                "spec": {"hard": policy["quota"]},
            }
            self.ensure_object(
                quota,
                self.core.create_namespaced_resource_quota,
                self.core.read_namespaced_resource_quota,
                name,
            )
        binding = {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {**metadata, "name": "sandbox-portal-access"},
            "roleRef": {
                "kind": "ClusterRole",
                "apiGroup": "rbac.authorization.k8s.io",
                "name": settings.namespace_access_role,
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": settings.portal_service_account,
                    "namespace": settings.portal_namespace,
                }
            ],
        }
        self.ensure_object(
            binding,
            self.rbac.create_namespaced_role_binding,
            self.rbac.read_namespaced_role_binding,
            name,
        )
        return name
