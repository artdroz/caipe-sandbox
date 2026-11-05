"""Explicit native fixture conversion for integration regression tests."""

from dataclasses import replace

from portal.integrations.agent_sandbox.inventory import describe
from portal.inventory import Sandbox


def as_sandbox(store, resource):
    if isinstance(resource, Sandbox):
        return resource
    observed = store.integrations.catalog.backend_for(resource).describe(resource)
    record = store.metadata.find_sandbox(observed.name, scope=observed.scope)
    if record is None:
        raise AssertionError("The test must create a database-backed sandbox first")
    sandbox = store._observe(record)
    return replace(
        sandbox,
        reference=resource,
        state=observed.state,
        message=observed.message,
        deleting=observed.deleting,
    )


def native_view(resource, generic=False):
    return describe(resource, "agentSandbox", generic=generic).view()
