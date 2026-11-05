"""Engineering image startup and file/service operations used by the portal."""

import argparse
import configparser
import fcntl
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import xmlrpc.client
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from configuration import digest, file_changes
from supervisor.options import ServerOptions
from supervisor.xmlrpc import Faults, SupervisorTransport

ROOT = Path(__file__).resolve().parent
MAX_FILE = 64 * 1024
MAX_FILES = 16
MAX_LOG = 64 * 1024
HOOK_TIMEOUT = 15
HOOK_BUDGET = 60


class WorkspaceError(Exception):
    def __init__(self, message, code=422):
        super().__init__(message)
        self.code = code


def directories():
    home = Path.home().resolve()
    config = home / ".config/sandbox"
    state = home / ".local/state/sandbox"
    for path in (
        config / "startup.d",
        config / "services.d",
        state / "logs",
        state / "seeded",
    ):
        if not path.resolve().is_relative_to(home):
            raise WorkspaceError(
                "micro VM configuration directories must stay inside home"
            )
        path.mkdir(parents=True, exist_ok=True)
    os.environ["SANDBOX_STATE"] = str(state)
    return config, state


def revision(content):
    return hashlib.sha256(content.encode()).hexdigest()


def atomic_write(path, content, mode=0o600):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".sandbox-")
    try:
        with os.fdopen(fd, "w") as output:
            output.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def file_path(kind, name):
    config, _ = directories()
    suffix = {"startup": ".sh", "service": ".conf"}.get(kind)
    if not suffix or not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,63}" + re.escape(suffix), name or ""
    ):
        raise WorkspaceError("Use a simple filename ending in .sh or .conf")
    path = config / ("startup.d" if kind == "startup" else "services.d") / name
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise WorkspaceError("Configuration must be a regular file")
    return path


def read_file(path):
    if path.is_symlink() or path.stat().st_size > MAX_FILE:
        raise WorkspaceError(
            "Configuration must be a regular UTF-8 file of at most 64 KiB"
        )
    try:
        return path.read_text()
    except UnicodeError:
        raise WorkspaceError("Configuration must be UTF-8 text") from None


@contextmanager
def workspace_lock():
    _, state = directories()
    with (state / "control.lock").open("a") as lock:
        deadline = time.monotonic() + 2
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise WorkspaceError(
                        "Another micro VM operation is in progress; retry", 409
                    ) from None
                time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def seed_home(services=(), seed_dirs=()):
    _, state = directories()
    defaults = load_record("defaults").get("files", {"startup": {}, "service": {}})
    home = Path.home()
    for source, target in (("bashrc", ".bashrc"), ("bash_profile", ".bash_profile")):
        if target == ".bash_profile" and any(
            (home / other).exists() for other in (".bash_login", ".profile")
        ):
            continue
        try:
            with (home / target).open("x") as output:
                output.write((ROOT / "defaults" / source).read_text())
        except FileExistsError:
            pass
    for name in services:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name):
            raise WorkspaceError("Invalid bundled service name")
        source = ROOT / "integrations" / name / "service.conf"
        if not source.is_file():
            raise WorkspaceError("Unknown bundled service: " + name)
        defaults.setdefault("service", {})[name + ".conf"] = source.read_text()
        marker = state / "seeded" / name
        if marker.exists():
            continue
        target = file_path("service", name + ".conf")
        if not target.exists():
            atomic_write(target, source.read_text())
        marker.touch(mode=0o600)

    for directory in seed_dirs:
        directory = Path(directory)
        for kind, folder, suffix in (
            ("startup", "startup.d", ".sh"),
            ("service", "services.d", ".conf"),
        ):
            sources = sorted((directory / folder).glob("*" + suffix))
            if len(sources) > MAX_FILES:
                raise WorkspaceError(
                    "Seed directories support at most 16 files per kind"
                )
            for source in sources:
                target = file_path(kind, source.name)
                defaults.setdefault(kind, {}).setdefault(
                    source.name, read_file(source.resolve())
                )
                marker = state / "seeded" / (kind + "-" + source.name)
                if marker.exists():
                    continue
                if not target.exists():
                    atomic_write(target, read_file(source.resolve()))
                marker.touch(mode=0o600)

    atomic_write(state / "defaults.json", json.dumps({"files": defaults}))


def run_hook(path, timeout):
    output = bytearray()
    process = subprocess.Popen(
        ["/bin/bash", str(path)],
        cwd=Path.home(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    output.extend(chunk)
                    del output[:-MAX_LOG]
    finally:
        if process.poll() is None or timed_out:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=2)
        process.stdout.close()

    return {
        "name": path.name,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "log": output.decode(errors="replace"),
    }


def run_startup():
    config, state = directories()
    results = []
    executed = {}
    deadline = time.monotonic() + HOOK_BUDGET
    for path in sorted((config / "startup.d").glob("*.sh"))[:MAX_FILES]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            results.append(
                {
                    "name": path.name,
                    "exit_code": None,
                    "timed_out": True,
                    "log": "Startup time budget exhausted",
                }
            )
            continue
        try:
            file_path("startup", path.name)
            executed[path.name] = read_file(path)
            results.append(run_hook(path, min(HOOK_TIMEOUT, remaining)))
        except (OSError, WorkspaceError) as exc:
            results.append(
                {
                    "name": path.name,
                    "exit_code": None,
                    "timed_out": False,
                    "log": str(exc),
                }
            )
    atomic_write(state / "startup.json", json.dumps(results))
    record_snapshot("startup", executed)
    return results


def supervisor_config():
    _, state = directories()
    return f"""[supervisord]
nodaemon=true
logfile={state}/supervisord.log
logfile_maxbytes=1MB
logfile_backups=1
pidfile={state}/supervisord.pid
childlogdir={state}/logs
[unix_http_server]
file={state}/supervisor.sock
chmod=0600
[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface
[supervisorctl]
serverurl=unix://{state}/supervisor.sock
[include]
files={state}/services.conf
"""


def validate_service(name, content):
    parser = configparser.RawConfigParser()
    try:
        parser.read_string(content)
    except configparser.Error:
        raise WorkspaceError("Invalid Supervisor configuration") from None
    expected = "program:" + name.removesuffix(".conf")
    if (
        parser.sections() != [expected]
        or not parser.get(expected, "command", fallback="").strip()
    ):
        raise WorkspaceError(
            "Service files need one [program:filename] section with a command"
        )
    _, state = directories()
    with tempfile.TemporaryDirectory(prefix="validate-", dir=state) as temporary:
        temporary = Path(temporary)
        (temporary / "service.conf").write_text(content)
        config = supervisor_config().replace(
            str(state / "services.conf"), str(temporary / "service.conf")
        )
        target = temporary / "supervisord.conf"
        target.write_text(config)
        try:
            ServerOptions().realize(["-c", str(target)])
        except (ValueError, SystemExit):
            raise WorkspaceError(
                "Supervisor rejected the service configuration"
            ) from None


def load_record(name):
    _, state = directories()
    path = state / (name + ".json")
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 3 * 1024 * 1024:
            return {}
        record = json.loads(path.read_text())
        return record if isinstance(record, dict) else {}
    except (OSError, ValueError):
        return {}


def source_files(kind):
    config, _ = directories()
    folder, suffix = (
        ("services.d", ".conf") if kind == "service" else ("startup.d", ".sh")
    )
    values, errors = {}, {}
    paths = sorted((config / folder).glob("*" + suffix))
    if len(paths) > MAX_FILES:
        errors["directory"] = "At most 16 files are supported per directory"
    for path in paths[:MAX_FILES]:
        try:
            file_path(kind, path.name)
            values[path.name] = read_file(path)
        except (WorkspaceError, OSError) as exc:
            errors[path.name] = str(exc)
    return values, errors


def saved_files(kind, source="applied"):
    if source == "default":
        return load_record("defaults").get("files", {}).get(kind, {})
    label = "services" if kind == "service" else "startup"
    return load_record(
        ("previous-" if source == "previous" else "applied-") + label
    ).get("files", {})


def record_snapshot(kind, files, native=None):
    _, state = directories()
    label = "services" if kind == "service" else "startup"
    old = load_record("applied-" + label)
    if old.get("files") != files and "files" in old:
        atomic_write(state / ("previous-" + label + ".json"), json.dumps(old))
    record = {
        "files": files,
        "revision": digest(files),
        "captured_at": datetime.now(UTC).isoformat(),
    }
    if native is not None:
        record["native_revision"] = digest(native)
    atomic_write(state / ("applied-" + label + ".json"), json.dumps(record))


def service_candidate():
    files, errors = source_files("service")
    for name, content in files.items():
        try:
            validate_service(name, content)
        except WorkspaceError as exc:
            errors[name] = str(exc)
    return files, errors


def service_configuration(files):
    return "\n\n".join(content.rstrip() for _, content in sorted(files.items())) + "\n"


def publish_services(files):
    _, state = directories()
    content = service_configuration(files)
    with tempfile.TemporaryDirectory(prefix="validate-", dir=state) as temporary:
        temporary = Path(temporary)
        (temporary / "services.conf").write_text(content)
        config = supervisor_config().replace(
            str(state / "services.conf"), str(temporary / "services.conf")
        )
        (temporary / "supervisord.conf").write_text(config)
        ServerOptions().realize(["-c", str(temporary / "supervisord.conf")])
    atomic_write(state / "services.conf", content)
    atomic_write(state / "supervisord.conf", supervisor_config())


def generated_drift(files):
    _, state = directories()
    try:
        return (state / "services.conf").read_text() != service_configuration(
            files
        ) or (state / "supervisord.conf").read_text() != supervisor_config()
    except OSError:
        return True


def prepare_services():
    files, errors = service_candidate()
    _, state = directories()
    atomic_write(
        state / "service-errors.json",
        json.dumps([{"name": name, "error": error} for name, error in errors.items()]),
    )
    if not errors:
        publish_services(files)
    return errors


def preview_services(manager):
    files, errors = service_candidate()
    repair = generated_drift(files)
    operations = []
    if not errors:
        publish_services(files)
        added, changed, removed = manager.reloadConfig()[0]
        autostart = {
            entry["group"]: entry["autostart"] for entry in manager.getAllConfigInfo()
        }
        for names, running in ((added, False), (changed, True)):
            for name in names:
                action = (
                    ("restart" if running else "start")
                    if autostart[name]
                    else ("update" if running else "add")
                )
                operations.append(
                    {"name": name, "filename": name + ".conf", "action": action}
                )
        operations.extend(
            {"name": name, "filename": name + ".conf", "action": "remove"}
            for name in removed
        )
    native = manager.getAllConfigInfo()
    groups = sorted({entry["group"] for entry in manager.getAllProcessInfo()})
    incomplete = bool(load_record("apply-error"))
    token = digest(
        {
            "files": files,
            "errors": errors,
            "native": native,
            "groups": groups,
            "operations": operations,
        }
    )
    return {
        "revision": token,
        "operations": operations,
        "errors": [{"name": name, "error": error} for name, error in errors.items()],
        "repair": repair,
        "runtime_changed": incomplete,
        "can_apply": not errors,
    }, files


def apply_services(expected):
    with supervisor() as connection:
        manager = connection.supervisor
        preview, files = preview_services(manager)
        if not expected or expected != preview["revision"]:
            raise WorkspaceError(
                "Configuration changed; review the service changes again", 409
            )
        if preview["errors"]:
            raise WorkspaceError("Fix invalid service files before applying", 422)
        _, state = directories()
        atomic_write(
            state / "apply-error.json",
            json.dumps(
                {
                    "message": "The previous apply did not finish. Review the remaining changes and apply again."
                }
            ),
        )
        for operation in preview["operations"]:
            if operation["action"] in {"remove", "restart", "update"}:
                manager.stopProcessGroup(operation["name"], False)
        deadline = time.monotonic() + 5
        for operation in preview["operations"]:
            name, action = operation["name"], operation["action"]
            if action in {"remove", "restart", "update"}:
                while True:
                    try:
                        manager.removeProcessGroup(name)
                        break
                    except xmlrpc.client.Fault as exc:
                        if exc.faultCode != Faults.STILL_RUNNING:
                            raise
                        if time.monotonic() >= deadline:
                            raise WorkspaceError(
                                "Services are still stopping; review and apply again",
                                409,
                            ) from None
                        time.sleep(0.1)
            if action != "remove":
                manager.addProcessGroup(name)
        record_snapshot("service", files, manager.getAllConfigInfo())
        atomic_write(state / "service-errors.json", "[]")
        (state / "apply-error.json").unlink(missing_ok=True)
    return {**inspect(), "applied": True}


def supervisor():
    _, state = directories()
    transport = SupervisorTransport(
        None, None, "unix://" + str(state / "supervisor.sock")
    )
    return xmlrpc.client.ServerProxy("http://localhost", transport=transport)


def inspect():
    _, state = directories()
    files = {}
    sources = {kind: source_files(kind) for kind in ("startup", "service")}
    for kind, (current, errors) in sources.items():
        files[kind] = file_changes(
            current,
            saved_files(kind),
            saved_files(kind, "previous"),
            saved_files(kind, "default"),
            errors,
        )
    with supervisor() as connection:
        manager = connection.supervisor
        services = [
            {
                key: entry[key]
                for key in ("name", "group", "statename", "description", "pid")
            }
            for entry in manager.getAllProcessInfo()
        ]
        old = load_record("applied-services")
        native_changed = bool(
            old.get("native_revision")
            and old["native_revision"] != digest(manager.getAllConfigInfo())
        )
        native_changed = native_changed or {entry["group"] for entry in services} != {
            name.removesuffix(".conf") for name in old.get("files", {})
        }
    known = {entry["name"] for entry in files["service"]}
    for entry in services:
        name = entry["group"] + ".conf"
        if name not in known:
            files["service"].append(
                {
                    "name": name,
                    "exists": False,
                    "revision": None,
                    "status": "untracked",
                    "recovery_sources": [],
                }
            )
            known.add(name)
    # Startup results use a list; keep their bounded on-disk representation.
    results = (
        json.loads((state / "startup.json").read_text())
        if (state / "startup.json").exists()
        else []
    )
    error_path = state / "service-errors.json"
    errors = json.loads(error_path.read_text()) if error_path.exists() else []
    return {
        "protocol_version": 1,
        "files": files,
        "services": services,
        "startup": [
            {key: result[key] for key in ("name", "exit_code", "timed_out")}
            for result in results
        ],
        "service_errors": errors,
        "active_drift": generated_drift(sources["service"][0]),
        "runtime_drift": native_changed or bool(load_record("apply-error")),
        "apply_error": load_record("apply-error").get("message")
        or (
            "Applied configuration history is missing. Review and apply to establish a new baseline."
            if services and "files" not in old
            else None
        ),
        "applied_at": old.get("captured_at"),
    }


def control(body):
    action = body.get("action")
    if action == "inspect":
        return inspect()
    if action in {"read", "save", "delete"}:
        path = file_path(body.get("kind"), body.get("name"))
        exists = path.exists()
        content = read_file(path) if exists else ""
        if action == "read":
            if not exists:
                raise WorkspaceError("Configuration file no longer exists", 404)
            return {"content": content, "revision": revision(content)}
        if (revision(content) if exists else None) != body.get("revision"):
            raise WorkspaceError("File changed; reload it before saving", 409)
        if action == "delete":
            if not exists:
                raise WorkspaceError("Configuration file no longer exists", 404)
            path.unlink()
            return {"deleted": True}
        new = body.get("content")
        if not isinstance(new, str) or len(new.encode()) > MAX_FILE or "\x00" in new:
            raise WorkspaceError("Configuration must be text of at most 64 KiB")
        if not exists and len(list(path.parent.glob("*" + path.suffix))) >= MAX_FILES:
            raise WorkspaceError("At most 16 files are supported per directory")
        if body["kind"] == "service":
            validate_service(path.name, new)
        atomic_write(path, new)
        return {"saved": True, "revision": revision(new)}
    if action == "preview":
        with supervisor() as connection:
            preview, _ = preview_services(connection.supervisor)
        return preview
    if action == "apply":
        return apply_services(body.get("preview_revision"))
    if action in {"read-version", "restore"}:
        kind, name = body.get("kind"), body.get("name")
        path = file_path(kind, name)
        source = body.get("source")
        if source not in {"applied", "previous", "default"}:
            raise WorkspaceError("Select a saved version")
        versions = saved_files(kind, source)
        if name not in versions:
            raise WorkspaceError("This saved version is no longer available", 404)
        content = versions[name]
        current = revision(read_file(path)) if path.exists() else None
        if action == "read-version":
            return {
                "content": content,
                "source_revision": revision(content),
                "revision": current,
                "current_content": read_file(path) if path.exists() else "",
            }
        if body.get("revision") != current or body.get("source_revision") != revision(
            content
        ):
            raise WorkspaceError(
                "File or saved version changed; reload it before restoring", 409
            )
        if kind == "service":
            validate_service(name, content)
        if (
            not path.exists()
            and len(list(path.parent.glob("*" + path.suffix))) >= MAX_FILES
        ):
            raise WorkspaceError("At most 16 files are supported per directory")
        atomic_write(path, content)
        return {"restored": True, "revision": revision(content)}
    if action in {"start", "stop", "restart", "logs"}:
        name = body.get("service", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name):
            raise WorkspaceError("Select a service")
        with supervisor() as connection:
            manager = connection.supervisor
            if action == "logs":
                return {"log": manager.readProcessStdoutLog(name, -MAX_LOG, 0)}
            if action in {"stop", "restart"}:
                manager.stopProcess(name, False)
            if action in {"start", "restart"}:
                if action == "restart":
                    deadline = time.monotonic() + 5
                    while manager.getProcessInfo(name)["statename"] in {
                        "RUNNING",
                        "STARTING",
                        "STOPPING",
                    }:
                        if time.monotonic() >= deadline:
                            raise WorkspaceError(
                                "Service is still stopping; refresh and retry", 409
                            )
                        time.sleep(0.1)
                manager.startProcess(name, False)
        return inspect()
    if action == "startup-logs":
        _, state = directories()
        results = (
            json.loads((state / "startup.json").read_text())
            if (state / "startup.json").exists()
            else []
        )
        return {
            "log": "\n".join(
                f"--- {result['name']} ---\n{result['log']}" for result in results
            )[-MAX_LOG:]
        }
    raise WorkspaceError("Unsupported micro VM operation")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["start", "control"])
    parser.add_argument("--service", action="append", default=[])
    parser.add_argument("--seed-dir", action="append", default=[])
    args = parser.parse_args()
    if args.mode == "start":

        def shutdown(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        seed_home(args.service, args.seed_dir)
        run_startup()
        errors = prepare_services()
        if errors:
            publish_services(saved_files("service"))
        else:
            files, _ = source_files("service")
            record_snapshot("service", files)
        _, state = directories()
        os.execvp("supervisord", ["supervisord", "-c", str(state / "supervisord.conf")])
    try:
        raw = sys.stdin.buffer.readline(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise WorkspaceError("micro VM request is too large")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise WorkspaceError("micro VM request must be an object")
        with workspace_lock():
            result = control(body)
    except WorkspaceError as exc:
        result = {"error": str(exc), "code": exc.code}
    except (OSError, ValueError, xmlrpc.client.Error, subprocess.TimeoutExpired):
        result = {
            "error": "micro VM service is unavailable; check startup and service configuration",
            "code": 503,
        }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
