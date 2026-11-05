# CAIPE Sandbox

Persistent environments for engineers and AI agents on Kubernetes. Select a
profile, choose resources and open a terminal. Use ordinary containers in an
existing development cluster, or add Kata and OpenShell for micro VM isolation
and runtime policy.

## Repository

| Path                                        | Purpose                                                                     |
| ------------------------------------------- | --------------------------------------------------------------------------- |
| `apps/portal/`                              | Portal API/UI, Dockerfile, metadata migrations and tests                    |
| `sandbox-images/common-tools/`              | Optional startup scripts and supervised-service support for workload images |
| `sandbox-images/default/`                   | Default workload Dockerfile; organizations can supply their own images      |
| `charts/caipe-sandbox/`                     | Installable portal chart with optional application dependencies             |
| `charts/agent-sandbox/`, `charts/omnigent/` | Optional application subcharts                                              |
| `docs/`                                     | Docusaurus guides and interactive architecture/configuration explorers      |

## Try the portal UI locally

Requires Python 3.12+, uv 0.12.17+, Node.js 24.22.1 and npm 11.11+.
The mock uses in-memory resources and fake identities; it needs no SSO or cluster.

```sh
make preview
```

Open <http://127.0.0.1:4193/agent-sandbox-portal/>. Create a sandbox, try
**Actions → Network & security**, inspect configuration and open a terminal.
Mock terminals simulate output and do not execute shell commands.

## Install

See the [packaging guide](docs/content/packaging.md). SQLite is included;
PostgreSQL is an external connection. Agent Sandbox, OpenShell, Omnigent and
Kata installation toggles default off. Operators provide storage, identity,
ingress and platform controllers. Both current runtime backends need an Agent
Sandbox controller, installed through the optional subchart or already present.

## Develop and contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for tests, images and releases. To run the
documentation and its interactive diagrams:

```sh
cd docs
npm ci --ignore-scripts
npm start -- --host 127.0.0.1 --port 3000 --no-open
```

Licensed under [Apache 2.0](LICENSE).
