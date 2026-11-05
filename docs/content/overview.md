---
title: What is CAIPE Sandbox?
description: Persistent environments for your tools and agents, managed through a shared portal.
---

CAIPE Sandbox is a portal for persistent micro VMs. A developer selects an
administrator-managed profile, chooses resources, and opens a terminal inside
an isolated environment. Tools and agents run in that environment; the portal
handles identity, access, inventory and lifecycle operations.

Start with [Concepts](concepts.md) for the terminology, or
[Get started](getting-started.md) to create your first sandbox.

## Three parts

| Part                | Responsibility                                                                              |
| ------------------- | ------------------------------------------------------------------------------------------- |
| Portal              | Sign-in, profile selection, access checks, resource bounds, sharing and lifecycle requests. |
| Runtime integration | Native provisioning, status, suspend/resume, deletion and terminal transport.               |
| Platform            | Cluster capacity, runtime installation, storage, admission, network controls and secrets.   |

The micro VM setup uses Kubernetes Agent Sandbox with a platform-installed
Kata runtime and an optional OpenShell integration. CAIPE and Omnigent are
examples of tools that can run inside a micro VM; neither defines
the portal's identity or architecture.

## Start with your role

- **Developer:** [create and use a micro VM](getting-started.md).
- **Administrator:** [understand profiles](profiles.md) and [deployment ownership](deployment.md).
- **Contributor:** [read the architecture](architecture.mdx) and explore the [code map](/guide/code-map).
- **Presenter:** open the [sandbox portal slides](/guide/slides).

The [packaging guide](packaging.md) also supports ordinary containers without
Kata. Those share the node kernel; a container profile does not create a micro VM.
