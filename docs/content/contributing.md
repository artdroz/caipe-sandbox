---
title: Contributing and releases
description: Find source boundaries, run local checks, and publish versioned images and charts.
---

The portal source and its Dockerfile are in `apps/portal`. Workload images live
under `sandbox-images`: `default/Dockerfile` builds the baseline image, and
`common-tools` holds shared startup/service scripts. Helm sources are in `charts`.
Portal adapters belong under `apps/portal/portal/integrations/<service>/`, with
matching browser integration code under `apps/portal/web/integrations/`.
Keep native service-specific behavior there; shared routes, storage and UI
contracts should remain reusable by other backends.

## Local development

Use Python 3.12 with uv, Node/npm and Helm 3.17+; install dependencies from the
committed lockfiles. From the repository root:

```sh
make preview  # Fake-identity portal at http://127.0.0.1:4193/agent-sandbox-portal/
make test     # Python, browser, export and chart checks
make docs     # Documentation tests and production build
```

The preview needs no SSO or Kubernetes credentials and must stay on loopback.
It cannot verify real controller, runtime or network enforcement. Set
`PORTAL_TEST_DATABASE_URL` to a disposable PostgreSQL database to run that engine's
tests too; CI supplies one. Never use a deployment database for tests.

Run `pre-commit run --all-files` before committing. Include images/video for UI
changes, verification results and the repo's complete PR template. Use Conventional
Commit PR titles and sign commits with your own DCO identity.

## Workload images and private extensions

`sandbox-images/default/Dockerfile` includes the shared `sandbox-start` and
`sandbox-control` tools. It does not install/sign into agent products. An
organization can derive a private image from it, add binaries and native
startup/service configuration, publish privately and reference its digest in a
deployment-managed profile. No portal fork is needed just to select a new image.

Keep private Dockerfiles, credentials and deployment values in their owning
repository. The [full contributor guide](https://github.com/caipe-io/caipe-sandbox/blob/main/CONTRIBUTING.md)
has image build commands and integration boundaries.

## CI and release artifacts

The workflow `.github/workflows/ci.yml` validates code/docs, tests both database
engines, packages the chart, and audits/scans images on native Linux amd64/arm64
runners. Pull requests publish no packages. Successful publish runs pin tested
multi-platform image digests into the chart.

| Trigger                           | Published artifacts                                                          |
| --------------------------------- | ---------------------------------------------------------------------------- |
| Pull request                      | Test/build artifacts for review; no registry publication.                    |
| Main push                         | Images tagged `sha-<commit>` and chart `<version>-dev.<commit>`.             |
| Matching `vMAJOR.MINOR.PATCH` tag | Versioned images and stable chart with the matching committed chart version. |

For a release, update the main chart's `version` and `appVersion` together,
merge the reviewed change, then push the matching version tag. The workflow
rejects mismatches. Document schema/CRD/runtime compatibility and required operator
actions in release notes. Protect release tags against replacement/deletion.

Packages live at `ghcr.io/<owner>/caipe-sandbox-portal`,
`ghcr.io/<owner>/caipe-sandbox-default` and
`oci://ghcr.io/<owner>/charts/caipe-sandbox`. Repository/package visibility and
Actions package-write permissions are administrative setup; CI does not make
private packages public. The docs job also deploys the static documentation to
GitHub Pages from main, independently of the image publication jobs. It uses the
site URL provided by GitHub; find the deployed URL on the workflow run or in
repository Settings → Pages. Pull requests and version tags do not deploy the
site; local documentation builds do not publish it.

Dependency updates retain the repository's release-age policy and reviewed
security/SDK exceptions. Track accepted vendor-dependent vulnerabilities explicitly
in GitHub; do not silently bypass the publication security gate.

## Configuration reference

The configuration reference pages and worked examples use definitions exported
from the chart and Python models. After changing those definitions, regenerate the reference
from the repository root:

```bash
uv run --project apps/portal --locked python docs/scripts/export-configuration-reference.py
```

Add explanations for new fields in
`docs/src/components/configuration/reference.mjs`. CI checks that the export is
current and every field has ownership and enforcement guidance. The exporter
reads checked-in defaults; it does not inspect credentials or a live deployment.
