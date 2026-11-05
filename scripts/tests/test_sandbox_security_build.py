import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "build/build-docker.sh"
SCANNER_IMAGE = "ghcr.io/aquasecurity/trivy@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c"


class SecurityBuildTests(unittest.TestCase):
    def run_build(self, dockerfile, failure=""):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text("""#!/bin/sh
printf 'docker %s\\n' "$*" >> "$COMMANDS"
if [ "$FAILURE" = audit ] && [ "$4" = --target ]; then exit 1; fi
if [ "$FAILURE" = build ] && [ "$4" = --tag ]; then exit 1; fi
if [ "$FAILURE" = pull ] && [ "$1" = pull ]; then exit 1; fi
case "$1 $2" in
  "image inspect")
    if [ "$FAILURE" = retag ] && [ -f "$COMMANDS.inspected" ]; then
      echo sha256:changed
    else
      echo sha256:tested
    fi
    touch "$COMMANDS.inspected" ;;
  "image save") touch "$4" ;;
esac
if [ "$1" = create ]; then echo helper-id; fi
if [ "$1" = inspect ]; then echo 0; fi
if [ "$1" = cp ] && [ "$2" = helper-id:/cache/reports/. ] && [ "$FAILURE" = report ]; then exit 1; fi
if [ "$1" = run ]; then
  case "$*" in
    *--download-db-only*) [ "$FAILURE" != db ] || exit 1 ;;
    *--format?json*) [ "$FAILURE" != scan ] && [ "$FAILURE" != findings ] || exit 1 ;;
    *convert*) [ "$FAILURE" != conversion ] || exit 1 ;;
  esac
fi
exit 0
""")
            docker.chmod(0o755)
            commands_file = root / "commands"
            result = subprocess.run(
                [
                    "bash",
                    str(SOURCE),
                    "--image",
                    "sandbox:test",
                    "--path",
                    dockerfile,
                    "--args",
                    "--platform linux/amd64",
                ],
                cwd=root,
                env={
                    **os.environ,
                    "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                    "COMMANDS": str(commands_file),
                    "FAILURE": failure,
                    "GITHUB_TOKEN": "test-token-must-not-be-forwarded",
                    "AWS_SECRET_ACCESS_KEY": "test-secret-must-not-be-forwarded",
                },
                capture_output=True,
                text=True,
            )
            return result, commands_file.read_text()

    def test_portal_audits_dependencies_then_scans_the_exported_image(self):
        result, commands = self.run_build("images/portal/Dockerfile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--target browser-audit", commands)
        self.assertIn("--target audit", commands)
        self.assertIn("--build-arg SECURITY_AUDIT_ID=", commands)
        self.assertLess(
            commands.index("--target audit"), commands.index("--tag sandbox:test")
        )
        self.assertIn("image inspect --format {{.Id}} sandbox:test", commands)
        self.assertIn("image save --output", commands)
        self.assertIn("--input /input/image.tar", commands)
        self.assertIn("--format json", commands)
        self.assertIn("--format cyclonedx", commands)
        self.assertIn("convert --ignorefile /dev/null --format table", commands)
        self.assertIn(
            "--severity CRITICAL,HIGH --ignore-unfixed --exit-code 1", commands
        )
        self.assertNotIn("docker push", commands)
        self.assertNotIn("accepted-vendor-risks.yaml", commands)

    def test_contributed_images_use_the_scan_without_the_portal_audit_target(self):
        result, commands = self.run_build(
            "images/example/Dockerfile"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--target audit", commands)
        self.assertNotIn("--target browser-audit", commands)
        self.assertIn("--exit-code 1", commands)
        self.assertNotIn("accepted-vendor-risks.yaml", commands)

    def test_scanner_is_pinned_restricted_and_offline_with_the_image(self):
        result, commands = self.run_build("images/portal/Dockerfile")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("docker pull " + SCANNER_IMAGE, commands)
        runs = [
            line for line in commands.splitlines() if line.startswith("docker run ")
        ]
        self.assertEqual(len(runs), 5)
        for run in runs:
            for flag in (
                "--user 65532:65532",
                "--read-only",
                "--cap-drop ALL",
                "--security-opt no-new-privileges:true",
                "--pids-limit 256",
            ):
                self.assertIn(flag, run)
        self.assertEqual(sum("--input /input/image.tar" in run for run in runs), 1)
        self.assertIn("target=/input,readonly", runs[2])
        for run in runs[2:]:
            self.assertIn("--network none", run)
        for run in runs[3:]:
            self.assertNotIn("target=/input", run)
        self.assertNotIn("docker.sock", commands)
        self.assertNotIn("type=bind", commands)
        self.assertNotIn("--privileged", commands)
        self.assertNotIn("GITHUB_TOKEN", commands)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", commands)
        self.assertNotIn("test-token-must-not-be-forwarded", commands)

    def test_database_download_has_no_image_and_uses_only_official_repositories(self):
        result, commands = self.run_build("images/portal/Dockerfile")
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [
            line for line in commands.splitlines() if line.startswith("docker run ")
        ]
        self.assertIn("--db-repository ghcr.io/aquasecurity/trivy-db:2", runs[0])
        self.assertIn(
            "--java-db-repository ghcr.io/aquasecurity/trivy-java-db:1", runs[1]
        )
        for run in runs[:2]:
            self.assertNotIn("target=/input", run)
            self.assertIn("--skip-version-check", run)
        self.assertIn("--skip-db-update --skip-java-db-update", commands)

    def test_failures_stop_publication_and_temporary_volumes_are_removed(self):
        for failure in (
            "audit",
            "build",
            "pull",
            "db",
            "scan",
            "findings",
            "conversion",
            "retag",
            "report",
        ):
            with self.subTest(failure=failure):
                result, commands = self.run_build(
                    "images/portal/Dockerfile", failure
                )
                self.assertNotEqual(result.returncode, 0)
                if failure == "audit":
                    self.assertNotIn("--tag sandbox:test", commands)
                if failure in {"audit", "build"}:
                    self.assertNotIn("docker pull ", commands)
                else:
                    self.assertIn("docker volume rm ", commands)
                if failure == "pull":
                    self.assertNotIn("docker run ", commands)
                if failure == "db":
                    self.assertNotIn("--input /input/image.tar", commands)
