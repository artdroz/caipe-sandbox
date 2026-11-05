"""Pin tested multi-platform images into one versioned Helm package."""

import argparse
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def release_version(ref, sha, chart_version):
    if ref.startswith("refs/tags/v"):
        version = ref.removeprefix("refs/tags/v")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", version):
            raise ValueError(
                "Release tags must use vMAJOR.MINOR.PATCH, optionally with a prerelease suffix"
            )
        if version != chart_version:
            raise ValueError("Release tag must match committed Chart.yaml version")
        return version
    if ref != "refs/heads/main" or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Publish only from main or a matching release tag")
    return f"{chart_version.split('-')[0]}-dev.{sha}"


def prepare(args):
    import yaml

    chart = ROOT / "charts/caipe-sandbox/Chart.yaml"
    values = ROOT / "charts/caipe-sandbox/values.yaml"
    metadata = yaml.safe_load(chart.read_text())
    if args.check and metadata["version"] != metadata["appVersion"]:
        raise ValueError("Committed chart version and appVersion must match")
    # Both image passes use the original committed version, recorded in appVersion.
    version = release_version(
        os.environ["GITHUB_REF"], os.environ["GITHUB_SHA"], metadata["appVersion"]
    )
    if args.check:
        return
    if (
        not args.image
        or not args.repository
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", args.digest or "")
    ):
        raise ValueError(
            "An image kind, repository and immutable SHA-256 digest are required"
        )
    config = yaml.safe_load(values.read_text())
    if args.image == "portal":
        config["image"] = {"repository": args.repository, "digest": args.digest}
    else:
        container = config["profiles"][0]["agentSandbox"]["spec"]["podTemplate"][
            "spec"
        ]["containers"][0]
        container.update(
            image=f"{args.repository}@{args.digest}", command=["sandbox-start"]
        )
        config["profiles"][0]["terminal"]["command"] = ["/bin/bash", "-l"]
    metadata["version"] = version
    chart.write_text(yaml.safe_dump(metadata, sort_keys=False))
    rendered = yaml.safe_dump(config, sort_keys=False)
    if config["image"].get("digest"):
        digest = config["image"]["digest"]
        rendered = rendered.replace(
            f"  digest: {digest}\n", f"  digest: {digest}  # Portal {version}\n", 1
        )
    host = config["profiles"][0]["agentSandbox"]["spec"]["podTemplate"]["spec"][
        "containers"
    ][0]
    if "caipe-sandbox-default@sha256:" in host["image"]:
        rendered = rendered.replace(
            f"image: {host['image']}\n",
            f"image: {host['image']}  # Default tools {version}\n",
            1,
        )
    values.write_text(rendered)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--image", choices=("portal", "default"))
    parser.add_argument("--repository")
    parser.add_argument("--digest")
    prepare(parser.parse_args())
