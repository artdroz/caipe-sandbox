import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "release", Path(__file__).parents[1] / "prepare-release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_main_packages_are_identified_by_exact_source_revision(self):
        sha = "a" * 40
        self.assertEqual(
            release.release_version("refs/heads/main", sha, "0.7.0"), "0.7.0-dev." + sha
        )

    def test_release_and_prerelease_tags_match_committed_version(self):
        for version in ("0.7.0", "0.7.0-rc.1"):
            self.assertEqual(
                release.release_version("refs/tags/v" + version, "a" * 40, version),
                version,
            )

    def test_untrusted_refs_and_mismatched_or_invalid_tags_are_rejected(self):
        for ref, sha, version in (
            ("refs/pull/1/merge", "a" * 40, "0.7.0"),
            ("refs/heads/main", "malformed", "0.7.0"),
            ("refs/tags/v0.8.0", "a" * 40, "0.7.0"),
            ("refs/tags/v../../evil", "a" * 40, "../../evil"),
        ):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                release.release_version(ref, sha, version)


class ReleasePackageTests(unittest.TestCase):
    def test_both_images_are_pinned_and_tag_mismatch_leaves_files_unchanged(self):
        import argparse
        import os
        import shutil
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chart = root / "charts/caipe-sandbox"
            chart.mkdir(parents=True)
            source = Path(__file__).parents[2] / "charts/caipe-sandbox"
            for name in ("Chart.yaml", "values.yaml"):
                shutil.copy2(source / name, chart / name)
            env = {"GITHUB_REF": "refs/tags/v0.8.0", "GITHUB_SHA": "a" * 40}
            args = argparse.Namespace(
                check=True, image=None, repository=None, digest=None
            )
            before = (chart / "values.yaml").read_text()
            with patch.object(release, "ROOT", root), patch.dict(os.environ, env):
                with self.assertRaises(ValueError):
                    release.prepare(args)
                self.assertEqual((chart / "values.yaml").read_text(), before)
                os.environ["GITHUB_REF"] = "refs/heads/main"
                for kind in ("portal", "default"):
                    args = argparse.Namespace(
                        check=False,
                        image=kind,
                        repository="ghcr.io/example/caipe-sandbox-" + kind,
                        digest="sha256:" + ("b" if kind == "portal" else "c") * 64,
                    )
                    release.prepare(args)
            text = (chart / "values.yaml").read_text()
            self.assertIn("ghcr.io/example/caipe-sandbox-portal", text)
            self.assertIn(
                "ghcr.io/example/caipe-sandbox-default@sha256:" + "c" * 64, text
            )
            self.assertIn("# Portal 0.7.0-dev." + "a" * 40, text)
            self.assertIn("# Default tools 0.7.0-dev." + "a" * 40, text)
            self.assertIn("- sandbox-start", text)
