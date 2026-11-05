import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import xmlrpc.client
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[3] / "sandbox-images/common-tools/sandbox/runtime.py"
sys.path.insert(0, str(SOURCE.parent))
spec = importlib.util.spec_from_file_location("sandbox_runtime", SOURCE)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.fixture
def home(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="sb-", dir="/tmp") as directory:
        monkeypatch.setenv("HOME", directory)
        monkeypatch.setenv(
            "PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
        )
        yield Path(directory)


def wait_for(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if result := predicate():
            return result
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for workspace state")


def save(kind, name, content, revision=None):
    return runtime.control(
        {
            "action": "save",
            "kind": kind,
            "name": name,
            "content": content,
            "revision": revision,
        }
    )


def test_home_defaults_preserve_user_files_and_deleted_services(home):
    runtime.seed_home(["omnigent"])
    assert "history -a; history -n" in (home / ".bashrc").read_text()
    (home / ".bashrc").write_text("# user preferences\n")
    service = runtime.file_path("service", "omnigent.conf")
    service.unlink()
    runtime.seed_home(["omnigent"])
    assert (home / ".bashrc").read_text() == "# user preferences\n"
    assert not service.exists()


def test_existing_login_and_profile_seed_files_are_preserved(home, tmp_path):
    (home / ".profile").write_text("# existing login\n")
    source = tmp_path / "startup.d"
    source.mkdir()
    (source / "10-setup.sh").write_text("echo initial\n")
    runtime.seed_home(seed_dirs=[tmp_path])
    assert not (home / ".bash_profile").exists()
    target = runtime.file_path("startup", "10-setup.sh")
    assert target.read_text() == "echo initial\n"
    target.unlink()
    runtime.seed_home(seed_dirs=[tmp_path])
    assert not target.exists()


def test_file_operations_conflicts_size_and_paths(home):
    first = save("startup", "10-work.sh", "echo one\n")
    with pytest.raises(runtime.WorkspaceError, match="File changed"):
        save("startup", "10-work.sh", "echo overwrite\n")
    second = save("startup", "10-work.sh", "echo two\n", first["revision"])
    assert (
        runtime.control({"action": "read", "kind": "startup", "name": "10-work.sh"})[
            "content"
        ]
        == "echo two\n"
    )
    with pytest.raises(runtime.WorkspaceError, match="File changed"):
        runtime.control(
            {
                "action": "delete",
                "kind": "startup",
                "name": "10-work.sh",
                "revision": first["revision"],
            }
        )
    runtime.control(
        {
            "action": "delete",
            "kind": "startup",
            "name": "10-work.sh",
            "revision": second["revision"],
        }
    )
    for name in ("../tokens.sh", "/tmp/evil.sh", "has spaces.sh", "bad.conf"):
        with pytest.raises(runtime.WorkspaceError):
            save("startup", name, "echo invalid")
    with pytest.raises(runtime.WorkspaceError):
        save("startup", "large.sh", "x" * (runtime.MAX_FILE + 1))
    target = runtime.file_path("startup", "link.sh")
    target.symlink_to(home / ".bashrc")
    with pytest.raises(runtime.WorkspaceError, match="regular file"):
        save("startup", "link.sh", "echo no")


def test_native_supervisor_validation_rejects_wrong_sections(home):
    for content in (
        "[supervisord]\n",
        "[program:other]\ncommand=sleep 1\n",
        "[program:example]\ncommand=sleep 1\nautostart=invalid\n",
    ):
        with pytest.raises(runtime.WorkspaceError):
            save("service", "example.conf", content)
    save("service", "example.conf", "[program:example]\ncommand=/bin/sleep 100\n")


def test_startup_order_failure_timeout_and_resume(home, monkeypatch):
    monkeypatch.setattr(runtime, "HOOK_TIMEOUT", 0.15)
    save("startup", "10-first.sh", 'echo first >> "$HOME/order"\n')
    save("startup", "20-fail.sh", "echo failure\nexit 4\n")
    save("startup", "30-timeout.sh", "sleep 10\n")
    save("startup", "40-last.sh", 'echo last >> "$HOME/order"\n')
    results = runtime.run_startup()
    assert [result["exit_code"] for result in results[:2]] == [0, 4]
    assert results[2]["timed_out"]
    assert results[3]["exit_code"] == 0
    assert (home / "order").read_text() == "first\nlast\n"
    runtime.run_startup()
    assert (home / "order").read_text() == "first\nlast\nfirst\nlast\n"


def test_real_supervisor_restart_apply_logs_and_shutdown(home):
    config = "[program:example]\ncommand=/bin/sleep 100\nstartsecs=0\nstopwaitsecs=1\nautorestart=true\nstopasgroup=true\nkillasgroup=true\n"
    saved = save("service", "example.conf", config)
    process = subprocess.Popen(
        [sys.executable, str(SOURCE), "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for(lambda: (home / ".local/state/sandbox/supervisor.sock").exists())

        def service():
            return next(iter(runtime.inspect()["services"]), {})

        first = wait_for(
            lambda: service() if service().get("statename") == "RUNNING" else None
        )
        os.kill(first["pid"], signal.SIGKILL)
        wait_for(lambda: service().get("pid") not in {0, first["pid"]})
        assert process.poll() is None
        runtime.control({"action": "stop", "service": "example"})
        wait_for(lambda: service().get("statename") == "STOPPED")
        assert process.poll() is None
        runtime.control({"action": "start", "service": "example"})
        wait_for(lambda: service().get("statename") == "RUNNING")
        assert isinstance(
            runtime.control({"action": "logs", "service": "example"})["log"], str
        )
        runtime.control(
            {
                "action": "delete",
                "kind": "service",
                "name": "example.conf",
                "revision": saved["revision"],
            }
        )
        assert runtime.control(
            {
                "action": "apply",
                "preview_revision": runtime.control({"action": "preview"})["revision"],
            }
        )["applied"]
        assert runtime.inspect()["services"] == []
        assert process.poll() is None
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=8)
        process.stderr.close()


def test_control_protocol_reads_one_line_without_waiting_for_stdin_eof(home):
    process = subprocess.Popen(
        [sys.executable, str(SOURCE), "control"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        process.stdin.write(
            json.dumps(
                {
                    "action": "save",
                    "kind": "startup",
                    "name": "example.sh",
                    "content": "echo ok\n",
                }
            )
            + "\n"
        )
        process.stdin.flush()
        process.wait(timeout=4)
        assert json.loads(process.stdout.read())["saved"]
    finally:
        process.stdin.close()
        process.stdout.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def test_drift_lists_new_changed_deleted_and_recoverable_files(home):
    from configuration import file_changes

    rows = file_changes(
        {"same.conf": "one", "changed.conf": "new", "new.conf": "new"},
        {"same.conf": "one", "changed.conf": "old", "deleted.conf": "old"},
        {"previous.conf": "old"},
        {"default.conf": "initial"},
    )
    statuses = {row["name"]: row["status"] for row in rows}
    assert statuses == {
        "same.conf": "applied",
        "changed.conf": "changed",
        "new.conf": "new",
        "deleted.conf": "deleted",
        "previous.conf": "recoverable",
        "default.conf": "recoverable",
    }
    assert next(row for row in rows if row["name"] == "deleted.conf")["exists"] is False


def test_invalid_candidate_preserves_supervisor_config_and_snapshot(home):
    original = "[program:example]\ncommand=/bin/sleep 100\n"
    save("service", "example.conf", original)
    assert not runtime.prepare_services()
    runtime.record_snapshot("service", {"example.conf": original})
    _, state = runtime.directories()
    before_config = (state / "services.conf").read_text()
    before = (state / "applied-services.json").read_bytes()
    runtime.file_path("service", "example.conf").write_text(
        "[program:example]\ncommand=/bin/sleep 100\nautostart=invalid\n"
    )
    assert runtime.prepare_services()
    assert (state / "services.conf").read_text() == before_config
    assert (state / "applied-services.json").read_bytes() == before


def test_failed_write_preserves_supervisor_configuration(home, monkeypatch):
    original = "[program:example]\ncommand=/bin/sleep 100\n"
    runtime.publish_services({"example.conf": original})
    _, state = runtime.directories()
    before = (state / "services.conf").read_text()
    write = runtime.atomic_write

    def fail(path, content, mode=0o600):
        if path == state / "services.conf":
            raise OSError("simulated disk error")
        return write(path, content, mode)

    monkeypatch.setattr(runtime, "atomic_write", fail)
    with pytest.raises(OSError):
        runtime.publish_services(
            {
                "example.conf": original.replace("100", "200"),
                "second.conf": "[program:second]\ncommand=/bin/sleep 100\n",
            }
        )
    assert (state / "services.conf").read_text() == before


def test_invalid_preview_reports_errors_without_planning_process_changes(home):
    runtime.file_path("service", "example.conf").write_text(
        "[program:example]\ncommand=/bin/sleep 100\nautostart=invalid\n"
    )
    manager = SimpleNamespace(getAllProcessInfo=lambda: [], getAllConfigInfo=lambda: [])
    preview, _ = runtime.preview_services(manager)
    assert not preview["can_apply"]
    assert preview["errors"][0]["name"] == "example.conf"
    assert not preview["operations"]


def test_failed_apply_retains_history_and_previews_remaining_native_changes(
    home, monkeypatch
):
    first = "[program:example]\ncommand=/bin/sleep 100\n"
    save("service", "example.conf", first)
    runtime.publish_services({"example.conf": first})
    runtime.record_snapshot("service", {"example.conf": first}, [])
    runtime.file_path("service", "example.conf").write_text(first.replace("100", "200"))
    _, state = runtime.directories()
    snapshot = (state / "applied-services.json").read_bytes()
    groups = {"example"}

    def add(name):
        raise xmlrpc.client.Fault(2, "simulated add failure")

    manager = SimpleNamespace(
        getAllProcessInfo=lambda: [{"group": name} for name in groups],
        getAllConfigInfo=lambda: [{"group": "example", "autostart": True}],
        reloadConfig=lambda: (
            [[[], ["example"], []]] if groups else [[["example"], [], []]]
        ),
        stopProcessGroup=lambda name, wait: None,
        removeProcessGroup=groups.remove,
        addProcessGroup=add,
    )
    monkeypatch.setattr(
        runtime, "supervisor", lambda: nullcontext(SimpleNamespace(supervisor=manager))
    )
    preview, _ = runtime.preview_services(manager)
    with pytest.raises(xmlrpc.client.Fault):
        runtime.apply_services(preview["revision"])
    assert "sleep 200" in (state / "services.conf").read_text()
    assert (state / "applied-services.json").read_bytes() == snapshot
    retry, _ = runtime.preview_services(manager)
    assert runtime.load_record("apply-error")
    assert retry["runtime_changed"]
    assert retry["operations"][0]["action"] == "start"


def test_restore_applied_previous_and_profile_default_with_conflict_checks(home):
    runtime.seed_home(["omnigent"])
    first = "[program:example]\ncommand=/bin/sleep 100\n"
    second = first.replace("100", "200")
    runtime.record_snapshot("service", {"example.conf": first})
    runtime.record_snapshot("service", {"example.conf": second})
    for source, expected in (("applied", second), ("previous", first)):
        viewed = runtime.control(
            {
                "action": "read-version",
                "kind": "service",
                "name": "example.conf",
                "source": source,
            }
        )
        restored = runtime.control(
            {
                "action": "restore",
                "kind": "service",
                "name": "example.conf",
                "source": source,
                **{key: viewed[key] for key in ("revision", "source_revision")},
            }
        )
        assert restored["restored"]
        assert runtime.file_path("service", "example.conf").read_text() == expected
    runtime.file_path("service", "omnigent.conf").unlink()
    viewed = runtime.control(
        {
            "action": "read-version",
            "kind": "service",
            "name": "omnigent.conf",
            "source": "default",
        }
    )
    runtime.control(
        {
            "action": "restore",
            "kind": "service",
            "name": "omnigent.conf",
            "source": "default",
            "revision": None,
            "source_revision": viewed["source_revision"],
        }
    )
    assert runtime.file_path("service", "omnigent.conf").exists()
    viewed = runtime.control(
        {
            "action": "read-version",
            "kind": "service",
            "name": "example.conf",
            "source": "applied",
        }
    )
    runtime.file_path("service", "example.conf").write_text(second)
    with pytest.raises(runtime.WorkspaceError, match="changed"):
        runtime.control(
            {
                "action": "restore",
                "kind": "service",
                "name": "example.conf",
                "source": "applied",
                **{key: viewed[key] for key in ("revision", "source_revision")},
            }
        )


def test_startup_snapshot_retains_deleted_script_for_recovery(home):
    save("startup", "10-first.sh", "echo first\n")
    runtime.run_startup()
    runtime.file_path("startup", "10-first.sh").unlink()
    assert runtime.saved_files("startup")["10-first.sh"] == "echo first\n"
    runtime.run_startup()
    assert runtime.saved_files("startup", "previous")["10-first.sh"] == "echo first\n"


def test_native_supervisor_plan_reports_exact_process_actions(home):
    save("service", "changed.conf", "[program:changed]\ncommand=/bin/sleep 200\n")
    save("service", "new.conf", "[program:new]\ncommand=/bin/sleep 100\n")
    save(
        "service",
        "stopped.conf",
        "[program:stopped]\ncommand=/bin/sleep 100\nautostart=false\n",
    )
    manager = SimpleNamespace(
        reloadConfig=lambda: [[["new", "stopped"], ["changed"], ["removed"]]],
        getAllProcessInfo=lambda: [
            {"group": name} for name in ("changed", "removed", "same")
        ],
        getAllConfigInfo=lambda: [
            {"group": name, "autostart": name != "stopped"}
            for name in ("new", "stopped", "changed", "same")
        ],
    )
    preview, _ = runtime.preview_services(manager)
    actions = {row["name"]: row["action"] for row in preview["operations"]}
    assert actions == {
        "changed": "restart",
        "removed": "remove",
        "new": "start",
        "stopped": "add",
    }


def test_real_preview_rejects_stale_apply_and_repairs_deleted_generated_config(home):
    first = "[program:example]\ncommand=/bin/sleep 100\nstartsecs=0\nstopwaitsecs=1\n"
    saved = save("service", "example.conf", first)
    process = subprocess.Popen(
        [sys.executable, str(SOURCE), "start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for(lambda: (home / ".local/state/sandbox/supervisor.sock").exists())
        preview = runtime.control({"action": "preview"})
        save("service", "example.conf", first.replace("100", "200"), saved["revision"])
        with pytest.raises(runtime.WorkspaceError, match="review"):
            runtime.control(
                {"action": "apply", "preview_revision": preview["revision"]}
            )
        before = runtime.saved_files("service")
        assert before["example.conf"] == first
        updated = runtime.control({"action": "preview"})
        assert updated["operations"][0]["action"] == "restart"
        runtime.control({"action": "apply", "preview_revision": updated["revision"]})
        assert runtime.saved_files("service", "previous") == before

        def running():
            services = runtime.inspect()["services"]
            return (
                services[0]
                if services and services[0]["statename"] == "RUNNING"
                else None
            )

        pid = wait_for(running)["pid"]
        content = first.replace("100", "200")
        save(
            "service",
            "example.conf",
            content + "# only a comment\n",
            runtime.revision(content),
        )
        comment = runtime.control({"action": "preview"})
        assert not comment["operations"]
        runtime.control({"action": "apply", "preview_revision": comment["revision"]})
        assert running()["pid"] == pid

        save(
            "service",
            "stopped.conf",
            "[program:stopped]\ncommand=/bin/sleep 100\nautostart=false\n",
        )
        added = runtime.control({"action": "preview"})
        assert added["operations"] == [
            {"name": "stopped", "filename": "stopped.conf", "action": "add"}
        ]
        runtime.control({"action": "apply", "preview_revision": added["revision"]})
        assert (
            next(
                row for row in runtime.inspect()["services"] if row["name"] == "stopped"
            )["statename"]
            == "STOPPED"
        )

        _, state = runtime.directories()
        (state / "services.conf").unlink()
        assert runtime.inspect()["active_drift"]
        repair = runtime.control({"action": "preview"})
        assert repair["repair"] and not repair["operations"]
        runtime.control({"action": "apply", "preview_revision": repair["revision"]})
        assert not runtime.inspect()["active_drift"]
        assert "sleep 200" in (state / "services.conf").read_text()
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=8)
        process.stderr.close()
