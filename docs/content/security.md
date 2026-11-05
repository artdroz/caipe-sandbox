---
title: Security
description: Isolation boundaries, workload restrictions, identity, sharing and persistent credentials.
---

Security spans portal authorization, workload isolation, Kubernetes permissions,
network boundaries and persisted data. Each layer has its own enforcement point.
Use [System architecture](architecture.mdx) to see where the boundaries sit and
[Code map](/guide/code-map) to find the responsible portal code.

## Layers of isolation

| Layer                    | What to validate                                                                    |
| ------------------------ | ----------------------------------------------------------------------------------- |
| Portal authorization     | Two users cannot operate on one another's private micro VMs.                        |
| Namespaces and RBAC      | Native resource access is limited to the intended identities and scopes.            |
| Pod admission            | Required runtime and security settings are admitted; unsafe overrides are rejected. |
| Runtime                  | The installed runtime provides the isolation properties your workload needs.        |
| Network                  | The CNI and policies block disallowed paths while permitting approved dependencies. |
| OpenShell, when selected | Native gateway policy and observed enforcement are verified independently.          |

An installed RuntimeClass name alone does not prove VM isolation. A configured
network policy alone does not prove traffic is denied. Use operator-owned tests
against the actual deployment.

## Workload restrictions

The direct Agent Sandbox backend validates profiles against the platform’s
approved runtime classes. Its profile validation also applies platform-owned
workload settings:

- The configured workload ServiceAccount, with token automount disabled.
- Host network, PID and IPC namespace sharing disabled.
- Privileged containers and privilege escalation disabled, with capabilities dropped.
- Host-path mounts and projected ServiceAccount tokens rejected.

These are checks and settings in the portal’s direct backend. The platform owns
runtime installation, cluster admission, RBAC, storage and network enforcement.
The selected Sandbox Provider owns its native provisioning and execution path;
provider-specific enforcement must be checked against that deployment.

See [Deployment ownership](deployment.md) for platform prerequisites.

## Portal identity and tool identity

The portal can use its own OIDC relying party. Identity comes from verified
authentication, not an owner value submitted by a browser. Domain restrictions,
group admission and role mapping are deployment choices. WebSocket terminals
also require authenticated access.

The portal's Kubernetes ServiceAccount is independent of the human login. Users
do not receive Kubernetes credentials through the portal. Native tool login runs
inside the micro VM and follows that tool's own credential lifecycle.

## Persistent credentials

CLI login caches can be written to the persistent micro VM. Apply ownership,
retention, backup and offboarding rules accordingly. Do not put passwords,
provider tokens or personal login state in a public profile, screenshot or log.

## Sharing

Explicit sharing is an authorization grant. Verify owner, recipient and requested
capability. Revoke grants when access is no longer needed. Administrative access
must be deliberately assigned and reviewed.
