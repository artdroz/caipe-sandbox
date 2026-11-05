"""Advertise a configured Omnigent startup service without inventing host health."""

from pathlib import PurePosixPath

from ..status import IntegrationStatus


class Status:
    def status(self, sandbox):
        manifest = (
            sandbox.record.manifest if sandbox.record else sandbox.reference or {}
        )
        spec = manifest.get("spec", {})
        if manifest.get("apiVersion") == "openshell.v1":
            commands = [spec.get("command", [])]
        else:
            spec = (sandbox.reference or manifest).get("spec", {})
            commands = [
                item.get("command", []) + item.get("args", [])
                for item in spec.get("podTemplate", {})
                .get("spec", {})
                .get("containers", [])
            ]
        for command in commands:
            if (
                command
                and PurePosixPath(command[0]).name == "sandbox-start"
                and (
                    "--service=omnigent" in command
                    or any(
                        part == "--service" and command[index + 1] == "omnigent"
                        for index, part in enumerate(command[:-1])
                    )
                )
            ):
                return IntegrationStatus(
                    id="omnigent",
                    title="Omnigent",
                    layer="Workload",
                    icon="omnigent",
                    state="configured",
                    detail="Omnigent startup service is configured. Login and server connection are not checked by this badge.",
                )
        return None
