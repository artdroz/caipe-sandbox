"""Export public configuration definitions, never deployment environment values."""

import argparse
import ast
from dataclasses import fields, replace
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/portal"))

from portal.commands import Probe  # noqa: E402
from portal.config import Settings  # noqa: E402
from portal.controls import GlobalPolicy, NamespaceControl, SandboxControl  # noqa: E402
from portal.profiles import Profile, Profiles  # noqa: E402
from portal.integrations.agent_sandbox.inventory import resolve  # noqa: E402
from portal.storage import Lease, SandboxRecord  # noqa: E402

DESTINATION = ROOT / "docs/src/components/configuration/reference.json"
MISSING = object()


def resolved(node, definitions):
    if "$ref" in node:
        return definitions[node["$ref"].split("/")[-1]]
    branches = [resolved(branch, definitions) for branch in node.get("anyOf", [])]
    for value in branches:
        if value.get("type") != "null":
            return {
                **value,
                **{k: v for k, v in node.items() if k != "anyOf"},
                "acceptedTypes": list(
                    dict.fromkeys(v.get("type", "value") for v in branches)
                ),
            }
    return node


def model_entries(model, prefix=""):
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})
    result = []

    def walk(raw, path, required=False, seen=()):
        node = resolved(raw, definitions)
        ref = raw.get("$ref")
        if ref in seen:
            return
        seen = (*seen, ref) if ref else seen
        properties = node.get("properties", {})
        if properties:
            for name, value in properties.items():
                walk(
                    value,
                    f"{path}.{name}" if path else name,
                    name in node.get("required", []),
                    seen,
                )
            return
        item = resolved(node.get("items", {}), definitions)
        if item.get("properties"):
            entry = {"path": path, "type": "array", "required": required}
            for key in ("minItems", "maxItems", "default"):
                if key in node:
                    entry[key] = node[key]
            result.append(entry)
            walk(item, path + "[]", seen=seen)
            return
        additional = node.get("additionalProperties")
        if isinstance(additional, dict) and resolved(additional, definitions).get(
            "properties"
        ):
            walk(additional, path + ".*", seen=seen)
            return
        entry = {
            "path": path,
            "type": node.get("acceptedTypes", node.get("type", "value")),
            "required": required,
        }
        for key in (
            "default",
            "enum",
            "pattern",
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
        ):
            if key in node:
                entry[key] = node[key]
        if "enum" in item:
            entry["itemChoices"] = item["enum"]
        result.append(entry)

    walk(schema, prefix)
    return result


def chart_entries(defaults, schema):
    result = []
    definitions = schema.get("definitions", {})

    def walk(default, raw, path):
        node = resolved(raw, definitions)
        props = node.get("properties", {})
        keys = dict.fromkeys([*(default if isinstance(default, dict) else {}), *props])
        dynamic_map = not props and "additionalProperties" in node
        if keys and path != "profiles" and not dynamic_map:
            for key in keys:
                child = (
                    default.get(key, MISSING) if isinstance(default, dict) else MISSING
                )
                walk(child, props.get(key, {}), f"{path}.{key}" if path else key)
            return
        entry = {
            "path": path,
            "type": node.get(
                "acceptedTypes",
                node.get(
                    "type",
                    type(default).__name__ if default is not MISSING else "value",
                ),
            ),
        }
        if default is not MISSING:
            entry["default"] = default
        for key in ("enum", "pattern", "minimum", "maximum", "minItems", "maxItems"):
            if key in node:
                entry[key] = node[key]
        result.append(entry)

    walk(defaults, schema, "")
    return result


def reference():
    chart = ROOT / "charts/caipe-sandbox"
    values = yaml.safe_load((chart / "values.yaml").read_text())
    schema = json.loads((chart / "values.schema.json").read_text())
    settings = Settings()
    openshell_values = yaml.safe_load(
        (ROOT / "apps/portal/examples/openshell.values.yaml").read_text()
    )
    examples = {
        "agentSandbox": values["profiles"][0],
        "openShell": openshell_values["profiles"][0],
        "native": {},
        "platform": {},
    }
    for backend in ("agentSandbox", "openShell"):
        connection = openshell_values["settings"]["openShell"]
        example_settings = replace(
            settings,
            profiles=json.dumps([examples[backend]]),
            default_profile=examples[backend]["id"],
            runtime_class="kata-qemu",
            allowed_runtime_classes='["kata-qemu"]',
            openshell_endpoint=connection["endpoint"],
            openshell_gateway_id=connection["gatewayId"],
            openshell_gateway_service_account=connection["gatewayServiceAccount"],
            openshell_runner_service_account=connection["sandboxServiceAccount"],
            openshell_supervisor_resources=json.dumps(
                connection["supervisorResources"]
            ),
        )
        catalog = Profiles(example_settings)
        profile = catalog.get()
        examples["platform"][backend] = {
            "defaultProfile": profile.id,
            "settings": {
                "runtimeClass": example_settings.runtime_class,
                "allowedRuntimeClasses": json.loads(
                    example_settings.allowed_runtime_classes
                ),
                "runnerServiceAccount": example_settings.runner_service_account,
                "sandboxSecurityContext": json.loads(
                    example_settings.sandbox_security_context
                ),
                "storageClass": example_settings.storage_class,
                **({"openShell": connection} if backend == "openShell" else {}),
            },
            "namespace": json.loads(example_settings.namespace),
            "resourcePolicy": json.loads(example_settings.resource_policy),
        }
        examples["native"][backend] = {}
        for name, cpu, memory in (("small", 500, 1024), ("medium", 1000, 2048)):
            size = catalog.size(profile).model_copy(
                update={"cpu_request_millicores": cpu, "memory_request_mib": memory}
            )
            native, snapshot = resolve(
                example_settings,
                "engineer@example.com",
                request_id="00000000-0000-4000-8000-000000000001",
                profile=profile,
                size=size,
                catalog=catalog,
            )
            examples["native"][backend][name] = {"spec": native["spec"]}
    environment = [
        {
            "path": "PORTAL_" + item.name.upper(),
            "type": type(getattr(settings, item.name)).__name__,
            "default": getattr(settings, item.name),
        }
        for item in fields(settings)
    ]
    env_names = {entry["path"] for entry in environment}
    for source in sorted((ROOT / "apps/portal/portal").rglob("*.py")):
        for call in ast.walk(ast.parse(source.read_text())):
            if not isinstance(call, ast.Call) or not call.args:
                continue
            function = ast.unparse(call.func)
            if function not in {"os.getenv", "os.environ.get"}:
                continue
            name = call.args[0]
            if (
                not isinstance(name, ast.Constant)
                or not isinstance(name.value, str)
                or name.value in env_names
            ):
                continue
            entry = {"path": name.value, "type": "process environment"}
            if len(call.args) > 1 and isinstance(call.args[1], ast.Constant):
                entry["default"] = call.args[1].value
            environment.append(entry)
            env_names.add(name.value)
    for template in sorted((chart / "templates").rglob("*")):
        if not template.is_file():
            continue
        for name in re.findall(
            r"^\s*-\s+name:\s+([A-Z][A-Z0-9_]+)\s*$", template.read_text(), re.MULTILINE
        ):
            if name not in env_names:
                environment.append({"path": name, "type": "chart wiring"})
                env_names.add(name)
    generated = model_entries(SandboxRecord, "record")
    generated += model_entries(GlobalPolicy, "admin")
    generated += model_entries(SandboxControl, "sandboxControl")
    generated += model_entries(NamespaceControl, "namespaceControl")
    generated += model_entries(Lease, "lease")
    generated += [
        {"path": "record.profile_snapshot." + key, "type": type(value).__name__}
        for key, value in snapshot.items()
    ]
    generated.append(
        {"path": "record.profile_snapshot.integration_configuration", "type": "object"}
    )
    generated += [
        {"path": path, "type": "observed", "required": False}
        for path in (
            "native.metadata.uid",
            "native.metadata.resourceVersion",
            "native.namespace.uid",
            "native.openshell.gateway_id",
            "native.openshell.sandbox_id",
            "native.openshell.policy_status.revision.version",
            "native.openshell.policy_status.active_version",
            "native.status",
            "correlation.request_id",
            "correlation.trace_id",
        )
    ]
    profile = model_entries(Profile)
    # Array item constraints are owned by the probe model even without a helper.
    assert set(Probe.model_fields) == {
        e["path"].split(".")[-1]
        for e in profile
        if e["path"].startswith("helpers[].status.")
    }
    return {
        "chartVersion": yaml.safe_load((chart / "Chart.yaml").read_text())["version"],
        "profile": profile,
        "deployment": chart_entries(values, schema),
        "environment": environment,
        "state": generated,
        "examples": examples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(reference(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != rendered:
            raise SystemExit(
                "Configuration reference is stale. Run: uv run --project apps/portal python docs/scripts/export-configuration-reference.py"
            )
        print(
            "Configuration reference matches chart values, profile models and portal metadata models"
        )
    else:
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        DESTINATION.write_text(rendered)


if __name__ == "__main__":
    main()
