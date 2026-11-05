---
title: Profiles and configuration
---

A profile is an administrator-managed preset. It supplies a workload image,
startup commands, environment, mounts, terminal behavior and optional helpers.
Profiles can target Agent Sandbox directly or select the OpenShell integration.

## Configuration has three owners

| Owner                 | Chooses                                                                                  | Does not imply                                              |
| --------------------- | ---------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Profile administrator | Image, commands, helpers, runtime selection and editable resource defaults/ranges.       | A helper installs its tool or authenticates the user.       |
| Developer             | Display name, offered profile and permitted resource sizes.                              | Arbitrary image, runtime, mount or security overrides.      |
| Platform operator     | Resource envelope, allowed runtimes, namespaces, storage, admission, egress and secrets. | Network isolation without compatible enforcement installed. |

**Profile defaults + permitted user choices + platform controls = effective configuration.**

Try those layers in the [configuration explorer](/guide/configuration).

## Resource controls

`ui.resources` declares `default`, `minimum` and `maximum` values for CPU and
memory requests/limits and micro VM storage. All three are required when this
section is supplied. Profile bounds must fit the platform's resource envelope.
The API checks requests as well as the browser.

The supported direct Agent Sandbox layout has one main container named `host`
and one persistent claim named `home`. `ui.resources` resolves into native
container requests/limits and claim storage. Do not duplicate its resource
defaults in the native profile spec.

CPU and memory changes are allowed only when fully suspended. Storage sizing
is a creation-time choice in the reference implementation.

## Retained profiles

New allocations use the current catalog. Existing micro VMs retain the profile
snapshot and configuration they were created with. Editing the catalog does
not silently rewrite their images, startup commands or permissions.

## Credentials and startup

Keep secrets in the platform's secret mechanism or the tool's native login
flow. Profiles and retained configuration are readable and must not contain
credentials. Initialization commands must tolerate retries. Mount the durable
micro VM where tools actually write their files and login state.

OpenShell adds native gateway, filesystem and network policy. Cluster admission
and namespace network policy remain platform responsibilities; configuring one
layer is not proof that every enforcement layer is operating.
