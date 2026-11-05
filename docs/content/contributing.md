---
title: Contributing and releases
---

The portal source is in `apps/portal`, reusable workload scripts are in
`packages/common-tools`, Dockerfiles are in `images`, and Helm sources are in
`charts`. Integration-specific code belongs in its named integration folder.

Use `make preview` for a local portal with fake resources and identity, `make test`
for regression checks and `make docs` to build this site. The preview does not
require an SSO session or Kubernetes credentials and must stay on loopback.

The GitHub Actions workflow validates PRs without publishing packages. Main builds
and matching version tags publish native amd64/arm64 images and an OCI chart to
GHCR. The chart pins the exact tested image manifests. Operators supply identity,
storage, ingress, secrets and any platform controllers.

Read the full [contributor guide](https://github.com/caipe-io/caipe-sandbox/blob/main/CONTRIBUTING.md)
for image customization, version tags, dependency policy and registry setup.
