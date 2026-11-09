"""Native operator-namespace prerequisites without direct workload egress grants."""

import json

from ...config import runner_pull_secrets
from .profile import supervisor_resources
from .volumes import enabled


def bootstrap(namespaces, name, metadata):
    settings = namespaces.settings
    resources = supervisor_resources(settings)
    if enabled(settings):
        namespaces.ensure_object(
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {**metadata, "name": "sandbox-openshell-storage"},
                "roleRef": {
                    "kind": "ClusterRole",
                    "apiGroup": "rbac.authorization.k8s.io",
                    "name": settings.namespace_access_role + "-openshell-storage",
                },
                "subjects": [
                    {
                        "kind": "ServiceAccount",
                        "name": settings.portal_service_account,
                        "namespace": settings.portal_namespace,
                    }
                ],
            },
            namespaces.rbac.create_namespaced_role_binding,
            namespaces.rbac.read_namespaced_role_binding,
            name,
        )
    namespaces.ensure_object(
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {**metadata, "name": settings.openshell_runner_service_account},
            "automountServiceAccountToken": False,
            "imagePullSecrets": runner_pull_secrets(settings),
        },
        namespaces.core.create_namespaced_service_account,
        namespaces.core.read_namespaced_service_account,
        name,
    )
    if json.loads(settings.namespace_policy).get("baselineNetworkPolicy", False):
        namespaces.ensure_network(
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {**metadata, "name": "sandbox-isolation"},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress", "Egress"],
                    "ingress": [],
                    "egress": [],
                },
            },
            name,
        )
    namespaces.ensure_object(
        {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {**metadata, "name": "openshell-sandbox-ssh"},
            "spec": {
                "podSelector": {
                    "matchLabels": {"openshell.ai/managed-by": "openshell"}
                },
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {
                                "namespaceSelector": {
                                    "matchLabels": {
                                        "kubernetes.io/metadata.name": settings.portal_namespace
                                    }
                                },
                                "podSelector": {
                                    "matchLabels": json.loads(
                                        settings.openshell_gateway_pod_selector
                                    )
                                },
                            }
                        ],
                        "ports": [{"protocol": "TCP", "port": 2222}],
                    }
                ],
            },
        },
        namespaces.networking.create_namespaced_network_policy,
        namespaces.networking.read_namespaced_network_policy,
        name,
    )
    namespaces.ensure_object(
        {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {**metadata, "name": "openshell-defaults"},
            "spec": {
                "limits": [
                    {
                        "type": "Container",
                        "defaultRequest": resources["requests"],
                        "default": resources["limits"],
                    }
                ]
            },
        },
        namespaces.core.create_namespaced_limit_range,
        namespaces.core.read_namespaced_limit_range,
        name,
    )
    namespaces.ensure_object(
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {**metadata, "name": "sandbox-openshell-access"},
            "roleRef": {
                "kind": "ClusterRole",
                "apiGroup": "rbac.authorization.k8s.io",
                "name": settings.namespace_access_role + "-openshell",
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": settings.openshell_gateway_service_account,
                    "namespace": settings.portal_namespace,
                }
            ],
        },
        namespaces.rbac.create_namespaced_role_binding,
        namespaces.rbac.read_namespaced_role_binding,
        name,
    )
