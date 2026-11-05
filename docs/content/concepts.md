---
title: Concepts
description: Sandboxes, profiles, providers, identity, sessions and persistence.
---

A sandbox is the environment you create and return to. A profile defines its
configuration; a provider manages its native resources. Terminals and tools run
against that environment.

## Sandbox, Pod and micro VM

The **sandbox** is the portal’s managed allocation: its owner, identity, selected
profile, resources and lifecycle. Its display name is separate from the native
resource identity.

A **Pod** runs the workload containers in Kubernetes. With a Kata runtime, the
workload runs inside a **micro VM**. The selected runtime determines this boundary;
a sandbox and a terminal session are not additional VMs. The deployment controls
which runtime classes profiles may use.

See [System architecture](architecture.mdx) for the runtime boundaries.

## Profiles and applied configuration

A **profile** is an administrator-managed preset. It defines the workload image,
startup behavior, environment, persistent mounts, terminal command and optional
helpers. It also selects a backend and can define editable resource bounds.

The **catalog** contains the profiles offered by the deployment. A developer
chooses a profile and resources within the offered limits. The platform supplies
capacity, approved runtimes, storage and enforcement.

An existing sandbox retains an **applied profile snapshot**. Updating the catalog
changes what new allocations use; it does not rewrite an existing sandbox’s image,
commands or helpers.

See [Profiles](profiles.md) and the
[worked configuration example](configuration-example.mdx).

## Sandbox Provider, runtime and tools

The **Sandbox Provider** owns native provisioning, observed status, lifecycle and
execution transport. Agent Sandbox and OpenShell are the current backend choices;
a profile selects exactly one. Provider adapters translate portal operations into
that backend’s API.

The **runtime** determines how the workload containers run. Kata supplies the
micro VM boundary. A tool or agent is a process supplied by the workload image;
adding a profile helper does not install the tool it invokes.

See [Code map](/guide/code-map) for the code behind these responsibilities.

## Identity, ownership and sharing

**Portal identity** establishes who is making a request and their portal role.
**Ownership** associates a sandbox with its owner. Explicit **sharing grants**
permit another user to view it or use its shell, subject to their role and policy.

The portal’s Kubernetes ServiceAccount is a separate identity used for cluster
operations. Tools inside the workload have their own login flows and credentials.
Signing in to the portal does not sign those tools in.

See [Security](security.md).

## Terminal sessions and processes

Opening another terminal creates another shell session in the same sandbox.
Those sessions use the same workload filesystem and resource allocation.
Creating another sandbox creates another allocation.

The portal relays each terminal connection and periodically rechecks access.
The actual shell, helper and agent processes run inside the workload. Suspension
interrupts sessions and stops execution; resuming requires new terminal sessions.

## State and persistence

Different kinds of state have different owners:

| State                                                | Current owner                   |
| ---------------------------------------------------- | ------------------------------- |
| Offered profile catalog                              | Deployment configuration        |
| Sandbox identity, owner, sharing and applied profile | Portal metadata database        |
| Global/per-user access policy and announcements      | Portal metadata database        |
| Workload files and saved tool credentials            | The workload’s persistent mount |
| Open terminals and process memory                    | Running sessions and processes  |

Persistent storage retains files, not running process memory. Tool login state
can survive when the tool writes it under the persistent mount; credentials may
still expire.

See [Database and persistence](metadata.md) for the active database scope.

## Putting the concepts together

1. Choose an offered profile and permitted resource sizes.
2. Create a sandbox. Its selected provider provisions the workload and storage.
3. Open two terminals. They are separate sessions in that same environment.
4. Write a file under the profile’s persistent mount, then suspend the sandbox.
5. Resume and open a new terminal. The file remains; the previous sessions and
   running processes do not resume from memory.

Continue with [Get started](getting-started.md) to use the portal.
