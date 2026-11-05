---
title: Install and upgrade
description: Choose optional chart dependencies, place workloads, and upgrade without losing state.
---

For a first installation, follow the [operator quickstart](getting-started.md).
This page covers packaging choices, optional dependencies and upgrades.

The main chart is `charts/caipe-sandbox`. A published chart archive
contains its dependencies; installation needs neither a source checkout nor
private charts. Helm and GitOps use the same values.

The [requirements and optional components table](getting-started.md#requirements-and-optional-components)
lists what the chart includes, the optional subcharts and the services an operator
provides. Dependency versions are pinned in the chart and its lockfile.

All integration installation toggles default off. Disabling installation still
allows connecting to an existing service. Both current runtime backends need
Agent Sandbox; enable its subchart or use an existing controller. Dependencies
follow the selected backend, rather than an unconditional core installation.

The operator supplies Kubernetes 1.30+, an enforcing CNI, storage, identity
provider and registry access. Ingress controllers, cert-manager, Vault/ESO,
Karpenter and telemetry services are operator-provided; none is installed here.
OpenShell retains its upstream PKI initialization option without cert-manager.

The release workflow builds Linux amd64 and arm64 images on native runners. Its `nodeSelector`, `affinity` and
`tolerations` configure portal placement independently of sandbox profiles and
integration charts; select compatible nodes when a cluster mixes architectures.

## Install from a published archive

After the first OSS package has been published, install a selected chart version
directly from OCI. Replace `PUBLISHED_CHART_VERSION` with that exact version:

```sh
helm upgrade --install sandbox oci://ghcr.io/caipe-io/charts/caipe-sandbox \
  --version PUBLISHED_CHART_VERSION \
  --namespace sandbox-system --create-namespace \
  -f development.values.yaml -f installation.yaml \
  --wait --timeout 10m
```

Published charts pin the tested portal and default workload image digests. Prepare
`installation.yaml` with the external origin, OIDC issuer/client configuration and
auth Secret reference as shown in the [quickstart](getting-started.md). If the
package has not been published, use its source-install instructions instead.

Use the included [development values](https://github.com/caipe-io/caipe-sandbox/blob/main/apps/portal/examples/development.values.yaml).
They install Agent Sandbox and use SQLite. Select the cluster's StorageClass if
there is no default. The auth Secret needs `client-secret` and `session-secret`.
The development values replace the profile catalog with a basic Python/shell
profile. They do not demonstrate the released image's startup/service tools.
For multiple replicas adapt the [external PostgreSQL values](https://github.com/caipe-io/caipe-sandbox/blob/main/apps/portal/examples/postgresql.values.yaml).
Give each installation its own database/PVC, auth configuration and unique
`settings.namespacePrefix`.

The PostgreSQL example selects RollingUpdate. On an empty database or a release
requiring migration, first use Recreate so the schema can be initialized/upgraded.
Switch to RollingUpdate only after confirming the schema already matches.

## Runtime and node placement

```yaml
settings:
  runtimeClass: ""
  allowedRuntimeClasses: [""]
```

An explicitly approved empty name uses the default runtime. The Pod's
`runtimeClassName` is null/omitted, not an empty RuntimeClass resource name.
Ordinary containers share the host kernel. They do not receive a Kata badge.
The saved configuration retains this choice when the platform default changes.

For Kata or another installed handler, set `runtimeClass` to its RuntimeClass
name and approve named classes through `allowedRuntimeClasses`. Profiles retain
native Pod `nodeSelector`, affinity and tolerations; Karpenter NodeClasses stay
operator-owned. There is no fallback after a named runtime fails.

`kata.enabled: true` uses the upstream node installer. Configure its native
node-selection and shim settings for compatible hosts; it is a cluster-wide
installation, not a per-portal runtime. Reuse an existing installation by leaving
it off. OpenShell additionally needs its kernel prerequisites and platform
approval of any requested RuntimeClass; enabling a chart does not prove those.

OpenShell's native empty `template.runtime_class_name` uses the gateway's default.
Leave `openShell.server.defaultRuntimeClassName` empty too when the intended
selection is the cluster's default runtime.

## Operator objects and network policies

`extraObjects` renders complete native Kubernetes objects without evaluating
strings as Helm templates. For example, an installed External Secrets Operator
can supply the portal's auth Secret:

```yaml
auth:
  existingSecret: portal-oidc
extraObjects:
  - apiVersion: external-secrets.io/v1
    kind: ExternalSecret
    metadata:
      name: portal-oidc
    spec:
      secretStoreRef:
        kind: ClusterSecretStore
        name: company-vault
      target:
        name: portal-oidc
      data:
        - secretKey: client-secret
          remoteRef: { key: sandbox/oidc, property: client-secret }
        - secretKey: session-secret
          remoteRef: { key: sandbox/oidc, property: session-secret }
```

Use API versions served by the operator's installed CRDs. These objects are
installation resources, not templates replicated into future sandbox namespaces.
The operator supplies baseline policies and their distribution to those namespaces.

`namespacePolicy.baselineNetworkPolicy` defaults to `false`; setting it to `true`
opts into the portal's `sandbox-isolation` baseline. Existing policies are not
deleted when the setting changes. OpenShell's native fences and gateway SSH rule
remain separate. Kubernetes NetworkPolicies combine allowed traffic; additional
broad egress grants selecting OpenShell workloads can weaken its outer fence.

## Source chart development

Application chart sources live in `charts/agent-sandbox` and `charts/omnigent`
alongside `charts/caipe-sandbox`. Update their versions and the main
dependency lock when changing them, then use native Helm:

```sh
helm dependency build charts/caipe-sandbox --skip-refresh
helm lint charts/caipe-sandbox -f development.values.yaml -f installation.yaml
helm package charts/caipe-sandbox
```

Use `helm dependency update` when intentionally changing dependency versions and
commit the reviewed lockfile. Source installs also need a built portal image's
repository/digest in `installation.yaml`.

OpenShell and Kata remain upstream chart dependencies. The Agent Sandbox CRD
and RBAC derive from upstream v1.0.5; its controller image is unchanged. CRDs in
the native `crds/` directory are installed before resources and retained on
uninstall. Helm does not upgrade them automatically: apply reviewed matching CRD
updates before changing controller API versions, following
[Helm's CRD lifecycle guidance](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/).
Install the shared controller
once per cluster and reuse it across portal releases.

## Upgrade an installation

1. Review the target release's schema, CRD and native runtime compatibility notes.
2. Back up the portal database and required workload/gateway state. Keep the old
   release version and deployment values; protect exports containing credentials.
3. Choose Recreate for SQLite or any required schema migration. Stop other writers
   using the database. PostgreSQL RollingUpdate is allowed only with an unchanged,
   already-current schema.
4. Apply reviewed CRD changes before their controller upgrade. Check shared
   controller impact on other installations.
5. Run the version-pinned Helm upgrade with your full deployment values and allow
   time for terminal draining. Verify init logs, readiness and a disposable sandbox.

The chart chooses migrate/check mode for each Pod's init container from the
Deployment strategy. There is no separate migration Job or Argo requirement.
[Database and persistence](metadata.md#schema-upgrades-and-replicas) explains locks,
old-writer shutdown and rollback limits. Helm rollback does not undo a database
migration.

A portal upgrade does not roll every existing workload image or replace its
applied profile snapshot. Updated catalog entries affect new creations; changes
to existing workloads require the supported, reviewed configuration/lifecycle
path. Native controller or gateway upgrades can have their own workload impact.

## Uninstall and retained state

Retire sandboxes through the portal while its controllers and access bindings
still exist, and verify the intended volume retention before removing the
installation. Removing the Helm release is not the portal's sandbox-deletion API.
The SQLite metadata PVC and native CRDs are retained; external databases are
operator-owned. Workload PVC behavior depends on their native resources and
storage policy. Reinstallation does not automatically adopt another release's
resources or restore a database backup.
