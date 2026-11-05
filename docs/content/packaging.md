---
title: Installing CAIPE Sandbox
---

The main chart is `charts/caipe-sandbox`. A published chart archive
contains its dependencies; installation needs neither a source checkout nor
private charts. Helm and GitOps use the same values.

| Component         | Installation                                                  |
| ----------------- | ------------------------------------------------------------- |
| Portal and SQLite | Core chart; SQLite uses one replica and a persistent volume   |
| PostgreSQL        | External URL or Secret reference; no database/operator chart  |
| Agent Sandbox     | Optional repo-owned application chart, `agentSandbox.enabled` |
| OpenShell         | Optional upstream 0.1.6 chart, `openShell.enabled`            |
| Omnigent          | Optional repo-owned application chart, `omnigent.enabled`     |
| Kata              | Optional upstream 4.2.0 chart, `kata.enabled`; off by default |

All integration installation toggles default off. Disabling installation still
allows connecting to an existing service. Both current runtime backends need
Agent Sandbox; enable its subchart or use an existing controller. Dependencies
follow the selected backend, rather than an unconditional core installation.

The operator supplies Kubernetes 1.30+, an enforcing CNI, storage, identity
provider and registry access. Existing ingress, cert-manager, Vault/ESO,
Karpenter and telemetry services can be referenced; none is installed here.
OpenShell retains its upstream PKI initialization option without cert-manager.
CAIPE embedding belongs to the next phase.

The release workflow builds Linux amd64 and arm64 images on native runners. Its `nodeSelector`, `affinity` and
`tolerations` configure portal placement independently of sandbox profiles and
integration charts; select compatible nodes when a cluster mixes architectures.

## Install from a published archive

After the first package has been published, retrieve it using native Helm:

```sh
helm pull oci://ghcr.io/caipe-io/charts/caipe-sandbox --version <published-version>
```

Published charts pin the tested portal and default workload image digests.
Create `installation.yaml` with the external origin, OIDC issuer/client
configuration and auth Secret reference. Source builds must also supply their
own portal image repository/digest.
For an existing cluster using ordinary Pods:

```sh
helm upgrade --install sandbox ./caipe-sandbox-0.7.0.tgz \
  --namespace sandbox-system --create-namespace \
  -f development.values.yaml -f installation.yaml \
  --wait --timeout 10m
```

Use the included [development values](https://github.com/caipe-io/caipe-sandbox/blob/main/apps/portal/examples/development.values.yaml).
They install Agent Sandbox and use SQLite. Select the cluster's StorageClass if
there is no default. The auth Secret needs `client-secret` and `session-secret`.
For multiple replicas use the existing [external PostgreSQL values](https://github.com/caipe-io/caipe-sandbox/blob/main/apps/portal/examples/postgresql.values.yaml).
Give each installation its own database/PVC, auth configuration and unique
`settings.namespacePrefix`.

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

## Source development and upgrades

Application chart sources live in `charts/agent-sandbox` and `charts/omnigent`
alongside `charts/caipe-sandbox`. Update their versions and the main
dependency lock when changing them, then use native Helm:

```sh
helm dependency update charts/caipe-sandbox
helm package charts/caipe-sandbox
```

OpenShell and Kata remain upstream chart dependencies. The Agent Sandbox CRD
and RBAC derive from upstream v1.0.5; its controller image is unchanged. CRDs in
the native `crds/` directory are installed before resources and retained on
uninstall. Helm does not upgrade them automatically: apply reviewed matching CRD
updates before changing controller API versions. Install the shared controller
once per cluster and reuse it across portal releases.

The portal's database schema is unchanged in 0.7.0. See [metadata upgrades](metadata.md)
for the Recreate/migrate and PostgreSQL rolling/check contracts. This chart does
not adopt another release's resources automatically.

Verify a fresh installation by creating a sandbox, opening a shell, writing a
file, suspending/resuming, checking the file, and deleting the sandbox. Check
`kubectl get networkpolicy -n <sandbox-namespace>` for the intended operator or
native runtime policies. Test the same flow separately with the approved Kata
and OpenShell profile before admitting pilot users.
