"""Native OpenShell gateway integration."""

from ...names import sandbox_name as sandbox_name
from . import policy as policy
from . import profile
from .namespaces import bootstrap
from .service import Integration, namespace_name

__all__ = ["profile", "bootstrap", "Integration", "namespace_name", "sandbox_name"]

key = "openShell"
reserved_prefixes = ("openshell.ai/",)


def supports_namespace(settings):
    return len(settings.namespace_prefix) <= 6


def namespace_labels(settings):
    return {settings.openshell_namespace_label: "true"}


def managed(resource):
    meta = resource.get("metadata", {})
    return (
        meta.get("labels", {}).get("openshell.ai/managed-by") == "openshell"
        or meta.get("annotations", {}).get("sandbox.caipe.io/backend") == "openShell"
    )
