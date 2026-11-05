---
title: Get started
description: The first micro VM journey for a developer.
---

You need access to an operator-provided portal and permission to use at least
one profile. The documentation preview does not provision a cluster or micro VM.

Read [Concepts](concepts.md) for the relationship between sandboxes, profiles,
providers and terminal sessions.

## 1. Sign in to your portal

Open the URL supplied by your operator. Portal sign-in establishes your identity
and role. Signing in to a tool inside the micro VM is a separate action.

## 2. Choose a profile and size

Select **New sandbox**, give it a display name, and choose an offered profile.
Pick CPU, memory and storage within the permitted bounds. A profile defines the
image, startup behavior, tools, helpers and terminal command.

Use the [configuration explorer](/guide/configuration) to see which choices belong
to the developer, profile administrator and platform operator.

## 3. Wait for readiness

Provisioning can involve node allocation, image downloads and disk attachment.
The portal reports observed state. A profile being configured does not prove
its workload or tools are ready.

## 4. Open a terminal and connect your tools

Once the micro VM is ready, open its terminal. Run the profile's login helper
when your tool needs authentication. Tools must already exist in the image;
declaring a helper does not install them or sign you in.

## 5. Suspend and resume

Save files to the profile's persistent micro VM path, then suspend. Resume
the same micro VM and check those files. Processes and open terminals do not
survive suspension; tool credentials may require another login.

Read [Micro VM lifecycle](workspaces.md) before deleting an environment.
