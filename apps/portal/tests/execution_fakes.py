"""An execution provider with no Kubernetes objects or client."""

from portal.execution import ExecutionTarget


def target(connector, *, incarnation="session-1"):
    return ExecutionTarget(
        key=("testRuntime", incarnation),
        scope="test-scope",
        sandbox_uid="sandbox-uid",
        connector=connector,
    )
