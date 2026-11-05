---
title: Deployment ownership
---

The portal source and Helm charts live in this repository. Start with the
[packaging guide](packaging.md) for installation, optional dependencies and
ordinary-container development deployments. Packages are published by the
repository workflow after merging; a source checkout alone does not publish them.

## Platform prerequisites

The current backends need an Agent Sandbox controller/CRDs, installed through
the optional chart or provided by the operator, plus an
approved runtime, worker capacity, persistent storage, admission controls, network
enforcement, portal image, TLS endpoint and identity configuration. OpenShell
profiles additionally need a compatible native gateway and its prerequisites.

## Keep deployment configuration separate

| Scope    | Configuration                                                                         |
| -------- | ------------------------------------------------------------------------------------- |
| Portal   | Origin/base path, OIDC, roles, metadata database and replica settings.                |
| Profile  | Workload image, native runtime configuration, startup, helpers and resource choices.  |
| Platform | Nodes, RuntimeClasses, storage, CNI, namespace policy, admission and secret delivery. |
| Tool     | Its server URL, native login flow and persistent credential path.                     |

For a separate portal hostname, the reference implementation uses an empty
`settings.basePath`, the configured HTTPS origin, OIDC mode and the exact
`/auth/callback` redirect registered at the identity provider.

## Acceptance before opening access

1. Verify an allowed identity can sign in and an unassigned identity is denied.
2. Create a disposable micro VM from an approved profile and inspect native readiness.
3. Open a terminal, run a helper and check tool authentication separately.
4. Suspend/resume and verify a file under the persistent micro VM remains.
5. Use a second identity to test ownership and explicit sharing boundaries.
6. Verify actual runtime isolation, disallowed network paths, backup and deletion behavior.

These are deployment checks. Building this documentation does not establish that
a cluster, portal or enforcement layer is running.

[Scaling documentation](scaling.md) is planned for a later update.
