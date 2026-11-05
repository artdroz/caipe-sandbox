# Contributing

Use small, focused pull requests with Conventional Commit titles. Run the
applicable checks below before committing. Include images or a video for visual
changes; describe the verification performed.

## Local checks

Python uses uv and a committed lock; the browser uses npm and a committed lock.
Both retain the existing 30-day dependency release delay and reviewed security
or SDK compatibility exceptions. Use the checked-in lockfiles for builds.

```sh
make test
make docs
```

`make test` runs Python, browser and chart checks. Helm 3.17+ is needed for
chart tests. Set `PORTAL_TEST_DATABASE_URL` to a disposable PostgreSQL database
to exercise that engine too; the SQLite contract always runs. CI supplies a
PostgreSQL service and runs both engines. No real Kubernetes credentials are
required for these checks.

For a loopback-only, fake-identity portal, use `make preview`. Do not expose
this development server or put the test harness in a production command.

## Images and private extensions

```sh
docker build -f apps/portal/Dockerfile -t sandbox-portal:local .
docker build -f sandbox-images/default/Dockerfile -t sandbox-default:local .
```

The default image contains a persistent shell and `sandbox-start` /
`sandbox-control`; it does not install or sign into agent products. A private
image can derive from it or copy `sandbox-images/common-tools/sandbox/`, add its own
binaries and startup/service files, and keep its Dockerfile and registry private.
Point the deployment-managed profile at that image's immutable digest. Neither
private image builds nor private deployment values belong in this repository.

Adapters stay under `portal/integrations/<service>/` and the matching browser
integration directory. Native API shapes stay in profiles; new integrations
should not add product-specific policy to core routes or storage.

## CI and releases

There is one workflow, `.github/workflows/ci.yml`, using GitHub-hosted runners:

1. Verify Python (SQLite/PostgreSQL), browser, packaged charts and documentation.
2. Build portal/default images on native Linux amd64 and arm64 runners. Audit
   dependencies and scan each final immutable image, keeping JSON reports/SBOMs.
3. On main or a version tag only, push the tested images to GHCR, combine their
   platform manifests and package the chart with those exact image digests.

Fork PRs need no organization secrets and publish nothing. Main publishes
`sha-<commit>` image tags and a unique `<chart version>-dev.<commit>` OCI chart.
For a release, update the main chart's `version` and `appVersion` together, merge
that change, then push a matching `vMAJOR.MINOR.PATCH` tag. The workflow rejects
mismatches. Stable tags are not moved by normal main builds; protect `v*` tags
with a repository ruleset and disallow updates/deletion.

Packages are `ghcr.io/<owner>/caipe-sandbox-portal`,
`ghcr.io/<owner>/caipe-sandbox-default` and
`oci://ghcr.io/<owner>/charts/caipe-sandbox`. These need package-write access for
GitHub Actions. Make the packages public when the repository is opened; the
workflow does not change repository or package visibility. No cloud account,
Vault, internal runners, SRE chart repository or release App token is required.

Review fixed HIGH/CRITICAL scan findings before publication. Unfixed/vendor
limitations must be tracked as a concrete accepted risk in GitHub; do not patch
vendor images or silently broaden exclusions. Scanner pinning, network-isolated
image scans and credential isolation are retained in `build/scan-image.sh`.

CRDs use native Helm `crds/` semantics: installation is automatic, upgrades
require an operator's reviewed CRD update. See the packaging guide for schema
migration and runtime choices. Database schema and backend behavior are unchanged
by the initial export.
