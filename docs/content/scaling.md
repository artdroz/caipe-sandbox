---
title: Scaling
---

SQLite supports one portal replica. For multiple replicas, configure an external
PostgreSQL database and a shared auth/session Secret. The chart can add a native
PodDisruptionBudget and topology spread. Use one application worker per Pod;
replication is at the Deployment level.

Each portal process has bounded terminal I/O workers, separate management workers,
database connections and independent WebSocket sessions. A shell stays on the
replica that accepted it. During replacement, the portal warns and drains its
sessions; the browser reconnects with bounded backoff. It does not replay helper
commands automatically. Runtime capacity and provider limits still apply.

A shell count is not an engineer count. Measure concurrent connections, terminal
throughput, queue delay, management latency, memory, native gateway behavior and
recovery under the actual ingress and cluster settings before setting capacity.
A local echo-transport benchmark cannot prove Kata/OpenShell workload capacity.
The existing harness is `apps/portal/tests/test_capacity.py`.

For engineer limits, `settings.maxSandboxesPerUser` counts every non-deleted
allocation owned by that engineer across namespaces/providers, including
suspended and unresolved creations. Zero disables that count limit. Set resource
bounds and cluster quotas separately.

See [metadata](metadata.md) for schema-aware upgrades and [deployment ownership](deployment.md)
for cluster prerequisites. Ordinary containers and Kata micro VMs have different
isolation and node overhead; neither profile guarantees node capacity.
