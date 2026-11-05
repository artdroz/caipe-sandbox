"""Sandbox policy editing through the native revision and admission contract."""

import json
from copy import deepcopy

from fastapi import HTTPException
from google.protobuf.json_format import ParseDict, ParseError
from openshell._proto import openshell_pb2 as pb
from openshell._proto import sandbox_pb2 as spb

from .client import data, scope

LIVE = ("network_policies", "network_middlewares")
REQUEST = "sandbox.caipe.io/policy-request-id"
STARTUP = ("filesystem", "landlock", "process")
BASELINE_PATHS = {
    "read_only": {"/usr", "/lib", "/etc", "/app", "/var/log", "/proc", "/dev/urandom"},
    "read_write": {"/tmp", "/dev/null"},
}
descriptor = {
    "id": "openshell",
    "title": "OpenShell",
    "icon": "openshell",
    "category": "security",
}


def supports_profile(profile):
    return getattr(profile, "openShell", None) is not None


def supports_sandbox(record):
    return record.provider == "openShell"


def creation_defaults(profile):
    return {
        "policy": {
            key: deepcopy(value)
            for key, value in profile.openShell.spec["policy"].items()
            if key in STARTUP
        }
    }


def prepare_creation(manifest, configuration):
    if (
        set(configuration) != {"policy"}
        or not isinstance(configuration["policy"], dict)
        or set(configuration["policy"]) - set(STARTUP)
        or any(
            not isinstance(value, dict) for value in configuration["policy"].values()
        )
    ):
        raise HTTPException(
            422,
            "Creation settings may only override filesystem, Landlock and process policy",
        )
    candidate = deepcopy(manifest)
    policy = {**candidate["spec"]["policy"], **configuration["policy"]}
    value = parsed(policy)
    for identity in (value.process.run_as_user, value.process.run_as_group):
        if (
            identity
            and identity != "sandbox"
            and not (
                identity.isascii()
                and identity.isdecimal()
                and len(identity) <= 10
                and 1 <= int(identity) <= 4294967294
            )
        ):
            raise HTTPException(
                422, "Process identity must be sandbox or a non-root numeric UID/GID"
            )
    for path in (*value.filesystem.read_only, *value.filesystem.read_write):
        if not path.startswith("/") or ".." in path.split("/"):
            raise HTTPException(
                422, "Filesystem paths must be absolute and cannot contain .."
            )
    if any(not path.strip("/") for path in value.filesystem.read_write):
        raise HTTPException(422, "Writable filesystem paths cannot include /")
    candidate["spec"]["policy"] = data(value)
    return candidate


def parsed(value):
    try:
        if not isinstance(value, dict):
            raise ValueError("Policy must be an object")
        if len(json.dumps(value, allow_nan=False).encode()) > 262144:
            raise ValueError("Policy exceeds 256 KiB")
        policy = ParseDict(value, spb.SandboxPolicy())
        if policy.version != 1:
            raise ValueError("Policy version must be 1")
        return policy
    except (ParseError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"Invalid OpenShell policy: {exc}") from None


def different(saved, current):
    expected, actual = parsed(saved), parsed(current)
    if expected.network_policies:
        # OpenShell persists available network baseline paths at startup.
        for access, baseline in BASELINE_PATHS.items():
            opposite = "read_write" if access == "read_only" else "read_only"
            declared = set(getattr(expected.filesystem, access))
            additions = (
                baseline - set(getattr(expected.filesystem, opposite)) - declared
            )
            getattr(actual.filesystem, access)[:] = sorted(
                set(getattr(actual.filesystem, access)) - additions
            )
            getattr(expected.filesystem, access)[:] = sorted(declared)
    return expected != actual


def snapshot(integration, cr):
    sandbox = integration.native(cr)
    config = integration.config(sandbox)
    status = integration.client.call(
        "GetSandboxPolicyStatus",
        pb.GetSandboxPolicyStatusRequest(
            workspace_scope=scope(sandbox.metadata.workspace),
            sandbox=sandbox.metadata.name,
        ),
    )
    return sandbox, config, status


def active(integration, sandbox, config, status):
    from .service import admitted

    return (
        status.revision.status == pb.POLICY_STATUS_LOADED
        and status.active_version == status.revision.version == config.version
        and admitted(sandbox, config)
    )


def read(integration, cr, record):
    sandbox, config, status = snapshot(integration, cr)
    base = data(status.revision.policy)
    saved = record.manifest["spec"]["policy"]
    drift = different(saved, base)
    admission = sandbox.status.configuration_admission
    rejected = (
        status.revision.status == pb.POLICY_STATUS_FAILED
        or admission.state == pb.CONFIGURATION_ADMISSION_STATE_REJECTED
    )
    applying = not rejected and (
        status.revision.status == pb.POLICY_STATUS_PENDING
        or admission.state == pb.CONFIGURATION_ADMISSION_STATE_PENDING
    )
    reason = ""
    if config.policy_source == spb.POLICY_SOURCE_GLOBAL:
        reason = "A platform OpenShell global policy is active. Sandbox policy editing is unavailable."
    elif sandbox.status.phase != pb.SANDBOX_PHASE_READY:
        reason = "Start the micro VM before editing its network policy."
    elif applying:
        reason = "Waiting for OpenShell to activate the saved policy."
    elif record.operation and not (
        record.operation.kind == "integration"
        and record.operation.state == "needs_attention"
        and status.revision.status != pb.POLICY_STATUS_PENDING
    ):
        reason = (
            "An operation is awaiting confirmation. Refresh or check application first."
        )
    state = (
        "managed"
        if config.policy_source == spb.POLICY_SOURCE_GLOBAL
        else "rejected"
        if rejected
        else "applied"
        if active(integration, sandbox, config, status) and not drift
        else "applying"
        if applying
        else "unknown"
    )
    profile = (record.profile_snapshot or {}).get("definition", {})
    return {
        "state": state,
        "detail": status.revision.load_error
        or config.configuration_error
        or admission.error,
        "editable": not reason,
        "reason": reason,
        "native_revision": f"policy:{status.revision.version}",
        "policy_version": status.revision.version,
        "active_version": status.active_version,
        "saved_policy": saved,
        "base_policy": base,
        "effective_policy": data(config.policy),
        "profile_policy": profile.get("openShell", {}).get("spec", {}).get("policy"),
        "drift": drift,
        "pending": bool(record.operation and record.operation.kind == "integration"),
    }


def plan(integration, cr, record, configuration, native_revision):
    current = read(integration, cr, record)
    if not current["editable"]:
        raise HTTPException(409, current["reason"])
    if current["native_revision"] != native_revision:
        raise HTTPException(409, "OpenShell policy changed; refresh and review again")
    if set(configuration) != {"policy"}:
        raise HTTPException(422, "Provide only the sandbox policy")
    candidate = data(parsed(configuration["policy"]))
    base = current["base_policy"]
    if {k: v for k, v in candidate.items() if k not in LIVE} != {
        k: v for k, v in base.items() if k not in LIVE
    }:
        raise HTTPException(
            422, "Filesystem, Landlock and process settings require sandbox recreation"
        )
    manifest = deepcopy(record.manifest)
    manifest["spec"]["policy"] = candidate
    return manifest, {
        "base_version": current["policy_version"],
        "base_policy": base,
    }


def apply(integration, cr, manifest, parameters, request_id):
    sandbox, config, status = snapshot(integration, cr)
    if config.policy_source == spb.POLICY_SOURCE_GLOBAL:
        raise HTTPException(409, "OpenShell policy is managed globally")
    target = parsed(manifest["spec"]["policy"])
    ours = status.revision.provenance.get(REQUEST) == str(request_id)
    unchanged = status.revision.version == parameters["base_version"]
    if not ours:
        if not unchanged or data(status.revision.policy) != parameters["base_policy"]:
            raise HTTPException(
                409,
                "OpenShell policy changed outside this operation; refresh and review again",
            )
        if status.revision.policy != target:
            integration.client.call(
                "UpdateConfig",
                pb.UpdateConfigRequest(
                    workspace_scope=scope(sandbox.metadata.workspace),
                    sandbox=sandbox.metadata.name,
                    policy=target,
                    expected_resource_version=sandbox.metadata.resource_version,
                    annotations={REQUEST: str(request_id)},
                ),
            )
            sandbox, config, status = snapshot(integration, cr)
    # Activation is asynchronous; the matching native revision confirms the save.
    if status.revision.policy != target:
        raise HTTPException(
            409,
            "Another OpenShell policy replaced this change; refresh and review again",
        )
