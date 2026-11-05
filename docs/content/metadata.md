---
title: Metadata and persistence
---

| Data                                                                         | Owner                                 |
| ---------------------------------------------------------------------------- | ------------------------------------- |
| Sandbox identity, owner, namespace membership, grants and desired manifest   | Portal SQLite/PostgreSQL database     |
| Operation journal, leases, resource reservations and administrative controls | Portal database                       |
| Current readiness, processes, native resources and policy activation         | Observed from the runtime integration |
| Workload files and tool credentials under the persistent mount               | Workload PVC/storage                  |
| Profile catalog offered for new allocations                                  | Deployment configuration              |

The database records intended state. Runtime adapters create and observe native
resources; the portal periodically reconciles supported Kubernetes resources
against the saved manifest. The interval defaults to 30 seconds and can be
configured or disabled. **Actions → View/Sync Configuration** offers a manual
refresh and an authorized sync with a diff. Syncing does not apply a newly changed
profile to an existing micro VM without review.

Namespace ownership belongs to its first sandbox creator. Subsequent sandboxes
keep their own creators. Namespace grants and the creation lock are separate
from VM ownership. Email identifies owners; sharing does not transfer ownership.

## Database choices

SQLite uses one portal replica and a durable volume. An external PostgreSQL URL
or Secret enables multiple replicas. The database can be dedicated within a
shared PostgreSQL service; no PostgreSQL operator is installed by this chart.
The storage interface, schema and migrations live under `apps/portal/portal/storage`.

Database transactions coordinate creation limits and desired state; operation
leases prevent two replicas from concurrently driving the same lifecycle action.
They do not make native provider calls exactly-once. An ambiguous response needs
observed-state verification before repeating a mutation. Full cross-provider
recovery and durable audit-history improvements remain future work.

## Schema upgrades

Alembic migrations are checked into `portal/storage/migrations/versions/`.
The application expects an exact schema version at startup.

- **Recreate:** old replicas stop, then each new Pod's init container runs
  `python -m portal.storage migrate`. Database locking serializes migration work;
  later replicas find the expected schema and continue.
- **RollingUpdate:** PostgreSQL only, when the schema is unchanged. The init
  container runs `check` and refuses readiness on a mismatch, with instructions
  to use Recreate for the migration. It does not migrate under old writers.

Use Recreate, a maintenance window and a backup for incompatible schema changes.
PostgreSQL does not automatically block old application versions. Portal upgrades
warn and drain terminal sessions for three minutes by default; workload Pods and
PVCs are separate and keep running. Reconnecting a shell does not restore its
process memory. A Helm rollback does not reverse a database migration.

## Backups

Take a database backup before schema changes and prove a restore into a separate
database. Keep auth/session configuration and profile GitOps configuration too.
A metadata backup does not include workload volumes: use the storage platform's
backup/snapshot mechanism and test attachment and access after restoration.
Never restore metadata over active portal writers or assume restoring it will
safely adopt unrelated native resources.
