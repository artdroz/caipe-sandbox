"""Explicit runtime registration; native behavior stays with each adapter."""

from fastapi import HTTPException

from . import agent_sandbox, kata, kubernetes, omnigent, openshell

PROVIDERS = (openshell,)
UI_INTEGRATIONS = (openshell.policy, kubernetes.policy)


def profile_ui(profile):
    return {
        item.descriptor["id"]: item
        for item in UI_INTEGRATIONS
        if item.supports_profile(profile)
    }


def sandbox_ui(record):
    return {
        item.descriptor["id"]: item
        for item in UI_INTEGRATIONS
        if item.supports_sandbox(record)
    }


def creation_ui(profile):
    return [
        {**item.descriptor, "creation": item.creation_defaults(profile)}
        for item in profile_ui(profile).values()
        if callable(getattr(item, "prepare_creation", None))
    ]


def prepare_creation(profile, manifest, configuration):
    configured = profile_ui(profile)
    for key, values in configuration.items():
        integration = configured.get(key)
        if integration is None or not callable(
            getattr(integration, "prepare_creation", None)
        ):
            raise HTTPException(
                422, "Integration is not available in the selected profile"
            )
        manifest = integration.prepare_creation(manifest, values)
    return manifest


def registered():
    return PROVIDERS


def profile_backend(profile):
    return next(
        (p for p in PROVIDERS if getattr(profile, p.key, None) is not None), None
    )


def namespace_backend(key):
    if key == "agentSandbox":
        return None
    provider = next((p for p in PROVIDERS if p.key == key), None)
    if provider is None:
        raise HTTPException(409, "Sandbox backend is unavailable; execution is blocked")
    return provider


class Integrations:
    def __init__(self, store, custom=None, core=None, namespaces=None):
        from .agent_sandbox.inventory import Inventory

        self.catalog = Inventory(store, custom, core, namespaces)
        self.items = {
            "agentSandbox": agent_sandbox.Integration(store, catalog=self.catalog)
        }
        self.items.update(
            {p.key: p.Integration(store, catalog=self.catalog) for p in PROVIDERS}
        )
        self.status_sources = (kata.Status(self.catalog), omnigent.Status())

    def status(self, sandbox, row):
        badges = {badge["id"]: badge for badge in row.get("integrations", [])}
        for source in getattr(self, "status_sources", ()):
            badge = source.status(sandbox)
            if badge is not None and badge.id not in badges:
                badges[badge.id] = badge.model_dump(exclude_none=True)
        row["integrations"] = list(badges.values())
        return row

    def for_profile(self, profile):
        provider = profile_backend(profile)
        return self.items[provider.key if provider else "agentSandbox"]

    def for_sandbox(self, sandbox):
        backend = self.items.get(sandbox.provider)
        if backend is None:
            raise HTTPException(
                409, "Sandbox backend is unavailable; execution is blocked"
            )
        return backend

    def execution(self, sandbox, *, admin=False):
        return self.for_sandbox(sandbox).execution(sandbox.reference, admin=admin)

    def retained_usage(self, owner, uids):
        usage = {}
        for backend in self.items.values():
            for key, value in backend.retained_usage(owner, uids).items():
                usage[key] = usage.get(key, 0) + value
        return usage

    def cleanup_namespaces(self):
        for backend in self.items.values():
            backend.cleanup()

    def close(self):
        for backend in self.items.values():
            backend.close()
