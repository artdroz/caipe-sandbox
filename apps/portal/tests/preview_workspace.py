"""In-memory Startup & services demo; never executes user scripts or services."""

import configparser
import hashlib
from copy import deepcopy
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from sandbox.configuration import digest, file_changes


def mock_service_plan(current, applied, groups):
    def options(content):
        parser = configparser.RawConfigParser()
        parser.read_string(content)
        return {section: dict(parser.items(section)) for section in parser.sections()}

    operations = []
    groups = set(groups)
    for filename in sorted(
        set(current) | set(applied) | {name + ".conf" for name in groups}
    ):
        name = filename.removesuffix(".conf")
        if filename not in current:
            action = "remove"
        elif name not in groups or options(current[filename]) != options(
            applied.get(filename, "")
        ):
            parser = configparser.RawConfigParser()
            parser.read_string(current[filename])
            autostart = parser.getboolean("program:" + name, "autostart", fallback=True)
            action = (
                ("restart" if name in groups else "start")
                if autostart
                else ("update" if name in groups else "add")
            )
        else:
            continue
        operations.append({"name": name, "filename": filename, "action": action})
    return operations


class PreviewWorkspace:
    def __init__(self):
        self.workspaces = {}
        self.lock = Lock()

    def run(self, target, body):
        with self.lock:
            return self.operation(target.sandbox_uid, body)

    def operation(self, name, body):
        if name not in self.workspaces:
            self.workspaces[name] = {
                "files": {
                    "startup": {
                        "10-startup.sh": '#!/bin/bash\nmkdir -p "$HOME/projects"\n'
                    },
                    "service": {
                        "omnigent.conf": (
                            Path(__file__).parents[3]
                            / "sandbox-images/common-tools/sandbox/integrations/omnigent/service.conf"
                        ).read_text()
                    },
                },
                "services": [
                    {
                        "name": "omnigent",
                        "statename": "RUNNING",
                        "description": "Mock process",
                        "pid": 314,
                    }
                ],
            }
        workspace = self.workspaces[name]
        if "applied" not in workspace:
            workspace["applied"] = deepcopy(workspace["files"])
            workspace["previous"] = {"startup": {}, "service": {}}
            workspace["defaults"] = deepcopy(workspace["files"])

        def inspect():
            return {
                "protocol_version": 1,
                "files": {
                    kind: file_changes(
                        files,
                        workspace["applied"][kind],
                        workspace["previous"][kind],
                        workspace["defaults"][kind],
                    )
                    for kind, files in workspace["files"].items()
                },
                "active_drift": False,
                "runtime_drift": False,
                "apply_error": None,
                "services": deepcopy(workspace["services"]),
                "startup": [
                    {"name": "10-startup.sh", "exit_code": 0, "timed_out": False}
                ],
                "service_errors": [],
            }

        def preview():
            groups = [entry["name"] for entry in workspace["services"]]
            return {
                "revision": digest(
                    {
                        "files": workspace["files"]["service"],
                        "applied": workspace["applied"]["service"],
                        "groups": groups,
                    }
                ),
                "operations": mock_service_plan(
                    workspace["files"]["service"],
                    workspace["applied"]["service"],
                    groups,
                ),
                "errors": [],
                "repair": False,
                "runtime_changed": False,
                "can_apply": True,
            }

        action = body["action"]
        if action == "inspect":
            return inspect()
        if action == "preview":
            return preview()
        if action in {"read-version", "restore"}:
            kind, filename, source = body["kind"], body["name"], body["source"]
            versions = workspace[
                {"applied": "applied", "previous": "previous", "default": "defaults"}[
                    source
                ]
            ][kind]
            if filename not in versions:
                raise HTTPException(404, "Saved version is no longer available")
            content = versions[filename]
            current = workspace["files"][kind].get(filename)
            current_revision = (
                hashlib.sha256(current.encode()).hexdigest()
                if current is not None
                else None
            )
            source_revision = hashlib.sha256(content.encode()).hexdigest()
            if action == "read-version":
                return {
                    "content": content,
                    "revision": current_revision,
                    "source_revision": source_revision,
                    "current_content": current or "",
                }
            if (
                body.get("revision") != current_revision
                or body.get("source_revision") != source_revision
            ):
                raise HTTPException(
                    409, "File or saved version changed; reload before restoring"
                )
            workspace["files"][kind][filename] = content
            return {"restored": True, "revision": source_revision}
        if action in {"read", "save", "delete"}:
            files = workspace["files"][body["kind"]]
            filename = body["name"]
            old = files.get(filename)
            revision = (
                hashlib.sha256(old.encode()).hexdigest() if old is not None else None
            )
            if action == "read":
                if old is None:
                    raise HTTPException(404, "File no longer exists")
                return {"content": old, "revision": revision}
            if revision != body.get("revision"):
                raise HTTPException(409, "File changed; reload it before saving")
            if action == "delete":
                files.pop(filename, None)
                return {"deleted": True}
            if body["kind"] == "service":
                parser = configparser.RawConfigParser()
                try:
                    parser.read_string(body["content"])
                    section = "program:" + filename.removesuffix(".conf")
                    if (
                        parser.sections() != [section]
                        or not parser.get(section, "command", fallback="").strip()
                    ):
                        raise ValueError("Service section must match the filename")
                    parser.getboolean(section, "autostart", fallback=True)
                except (configparser.Error, ValueError):
                    raise HTTPException(
                        422, "Invalid Supervisor configuration"
                    ) from None
            files[filename] = body["content"]
            return {
                "saved": True,
                "revision": hashlib.sha256(body["content"].encode()).hexdigest(),
            }
        if action == "apply":
            proposed = preview()
            if body.get("preview_revision") != proposed["revision"]:
                raise HTTPException(
                    409, "Configuration changed; review the service changes again"
                )
            workspace["previous"]["service"] = deepcopy(workspace["applied"]["service"])
            workspace["applied"]["service"] = deepcopy(workspace["files"]["service"])
            for operation in proposed["operations"]:
                workspace["services"] = [
                    entry
                    for entry in workspace["services"]
                    if entry["name"] != operation["name"]
                ]
                if operation["action"] != "remove":
                    workspace["services"].append(
                        {
                            "name": operation["name"],
                            "statename": "STOPPED"
                            if operation["action"] in {"add", "update"}
                            else "RUNNING",
                            "description": "Mock process",
                            "pid": 314,
                        }
                    )
            return {**inspect(), "applied": True}
        if action in {"start", "stop", "restart"}:
            for service in workspace["services"]:
                if service["name"] == body["service"]:
                    service["statename"] = "STOPPED" if action == "stop" else "RUNNING"
                    service["pid"] = 0 if action == "stop" else 314
            return inspect()
        if action in {"logs", "startup-logs"}:
            return {
                "log": "Mock preview — no commands are executed.\n"
                + (
                    "10-startup.sh completed successfully.\n"
                    if action == "startup-logs"
                    else "Service waiting for login / running.\n"
                )
            }
        raise HTTPException(422, "Unsupported preview action")
