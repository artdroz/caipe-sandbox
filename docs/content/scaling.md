---
title: Capacity and scaling
description: Scale portal replicas, bound resource use, and test terminal capacity and recovery.
---

Scale the portal and the workload fleet separately. More portal replicas add API
and terminal-forwarding capacity; they do not create more workload nodes, increase
a gateway's limits or make a single SQLite file suitable for multiple replicas.

## Portal replicas

| Concern               | SQLite                   | External PostgreSQL                                                              |
| --------------------- | ------------------------ | -------------------------------------------------------------------------------- |
| Portal replicas       | Exactly one.             | Multiple replicas share the same database.                                       |
| Application processes | One worker per Pod.      | One worker per Pod; add Pods to scale.                                           |
| Upgrade strategy      | Recreate.                | Recreate for schema changes; RollingUpdate only when the schema already matches. |
| Session configuration | One auth/session Secret. | The same auth/session Secret and identity policy across replicas.                |

Use the [PostgreSQL example values](https://github.com/caipe-io/caipe-sandbox/blob/main/apps/portal/examples/postgresql.values.yaml)
as a starting point for two replicas. Initialize/migrate the database with Recreate
before selecting RollingUpdate. Set topology-spread label selectors to your actual
Helm release name; the chart's Pod label is `app.kubernetes.io/name: <release>`.

The chart enables a PodDisruptionBudget only with multiple replicas. It helps
bound voluntary evictions, not node failure or a Deployment's own rollout;
see [Kubernetes disruption behavior](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/).
Topology spread also needs enough eligible nodes. Neither setting proves high
availability of the external database or native gateway.

## Terminals and shutdown

A WebSocket stays on the portal replica that accepted it. Session streams are not
stored in SQL or handed live to another replica. Each process has:

- Async tasks for each terminal's input, output and access revalidation.
- A dedicated bounded pool for blocking terminal I/O, configured by
  `settings.terminalIoWorkers` (default **32**).
- Separate management work through Python's default executor, plus a bounded SQL
  connection pool. Management worker/pool sizing is not a second group of Pods.

The terminal worker count is not a shell-count limit: threads service blocking
calls across sessions. Measure queueing and throughput before increasing it;
more threads also consume memory and backend resources. The SQL store's default
pool is five connections per process with no overflow; additional replicas need
database connection headroom, including during migrations and rollouts.

During an orderly shutdown, readiness fails, new work is rejected and connected
terminals receive a warning/countdown. Browser notifications require user
permission. The chart defaults are:

| Value                           | Default | Purpose                                         |
| ------------------------------- | ------- | ----------------------------------------------- |
| `shutdown.propagationSeconds`   | 10      | Allow routing/readiness changes to propagate.   |
| `shutdown.drainSeconds`         | 180     | Time for users to finish terminal work.         |
| `shutdown.serverGraceSeconds`   | 30      | Application shutdown allowance.                 |
| `terminationGracePeriodSeconds` | 240     | Must exceed the sum of the three budgets above. |

The browser retries ordinary shell connections with bounded backoff. Reconnection
opens a **new shell**, without replaying commands or restoring process memory;
helpers are not automatically rerun. A node crash or forced Pod deletion may skip
the warning/drain window. A healthy second replica helps users reconnect but
does not preserve the lost stream. See [Database and persistence](metadata.md)
for the separate workload and database state boundaries.

## Limits and workload capacity

```yaml
settings:
  maxSandboxesPerUser: 5
```

This example limits each creator to five non-deleted allocations across all
namespaces/backends, including suspended and unresolved creations. The repository
default is **0**, which disables this count limit. Sharing does not transfer
ownership or move an allocation to another engineer's quota.

Also set profile/UI resource ranges, the platform `resourcePolicy`, namespace
quotas and cluster capacity budgets. Count limits do not impose an organization
spend ceiling or reclaim idle workloads. There is no general automatic idle
suspension or warm pool in the portal. Kata and ordinary containers have different
node requirements and overhead; persistent volumes still cost capacity while
compute is suspended.

## Measure before opening a larger cohort

A shell count is not an engineer count. Measure concurrent connections, terminal
throughput, queue delay, management latency, memory, native gateway behavior and
recovery under the actual ingress and cluster settings before setting capacity.
A local echo-transport benchmark cannot prove Kata/OpenShell workload capacity.
The local forwarding harness is `apps/portal/tests/test_capacity.py`. It uses two
portal processes and a disposable PostgreSQL test database with a fake transport:

```sh
cd apps/portal
uv sync --locked --extra test --no-install-project --no-build
# Set PORTAL_TEST_DATABASE_URL to a disposable PostgreSQL database first.
PORTAL_CAPACITY_BENCHMARK=1 PORTAL_CAPACITY_SHELLS=50,100,200 \
  uv run --locked --no-sync python -m pytest -q tests/test_capacity.py
```

The harness creates test state; never point it at a deployed portal database.
JSON-line results default to `/tmp/portal-capacity.jsonl`; set
`PORTAL_CAPACITY_REPORT` to choose another path. It measures forwarding and
management behavior, not real workload isolation or native-provider limits.

For deployment acceptance, stage a small number of disposable workloads through
the actual ingress and selected backend. Increase load only while latency, errors,
CPU/memory and gateway/database pressure stay within your chosen thresholds.
Include one controlled portal replacement, policy changes, lifecycle operations
and cleanup under load. Record the tested image/chart/runtime versions and
concurrency; do not turn a local benchmark result into a universal engineer limit.
