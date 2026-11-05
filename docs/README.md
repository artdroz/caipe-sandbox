# Documentation site

This Docusaurus 3 site accompanies the CAIPE Sandbox portal, workload tools and
Helm charts. It includes configuration references, a code map and an architecture
playground.

## Develop

```sh
cd docs
npm ci
npm start -- --host 127.0.0.1 --port 3000 --no-open
```

## Verify

```sh
npm test
npm run build
npm run serve -- --host 127.0.0.1 --port 3000 --no-open
```

The production build fails on broken site and Markdown links. In the browser,
check Guide navigation, configuration search and sizing, code-map selections,
architecture interactions, dark mode, and a narrow/mobile viewport.

Production builds generate their registry and route metadata in
`.docusaurus-build/`; the live development server uses `.docusaurus/`. This keeps
`npm run build` from replacing the preview’s generated modules during development.

If a browser retains a missing-chunk error after a server restart, reload the
page. To reset development metadata, stop the preview, run `npm run clear`, and
start it again with the command above.

## Structure

- `content/`: Markdown and MDX guides, ordered by `sidebars.js`.
- `src/pages/`: home and redirects for supported older documentation URLs.
- `src/components/`: interactive documentation components.
- `src/css/custom.css`: shared styling and responsive layouts.
- `static/img/`: local branding assets.
- `docusaurus.config.js`: navigation and site settings.

The site accompanies the portal, charts and workload tools included in this repository.
Example configuration uses placeholders; see the packaging guide for installation.

Local `npm start`, `npm run build`, and `npm run serve` commands do not publish.
The main branch's CI reads the site's origin and base path from GitHub Pages,
builds with `DOCS_URL` / `DOCS_BASE_URL`, uploads the static site and deploys it
through the `github-pages` environment. The deployment URL appears on the workflow
run and in repository Settings → Pages; private organization sites can use a
generated hostname instead of the public project URL. PRs validate the public
`/caipe-sandbox/` subpath build but cannot deploy. Version tags publish application packages without replacing the
documentation site. Repository Settings → Pages must use GitHub Actions as its
source; no deployment branch or personal access token is required.

To test the production subpath locally:

```sh
DOCS_BASE_URL=/caipe-sandbox/ npm run build
DOCS_BASE_URL=/caipe-sandbox/ npm run serve -- --host 127.0.0.1 --port 3001 --no-open
```

Open <http://127.0.0.1:3001/caipe-sandbox/> and check navigation, branding assets,
direct Guide links, and the interactive diagrams.

## System architecture

Open `guide/architecture` for the main system architecture playground. The navbar,
home page and documentation sidebar lead to this single view. The code map
remains a separate implementation reference.

Agent Sandbox is checked and disabled as a required component. Kata is optional
and selected by default; toggling it updates the Pod boundary label and its
Kata/padlock badge. Omnigent and OpenShell remain optional. The interaction dropdown groups portal,
native-runtime and Omnigent flows, including separate browser sign-in, runner
registration and work over the existing host tunnel.

Click a component for deployment location, identity/state ownership and connection
details below the diagram. **Wide view** gives the diagram more space; Escape
exits it. Paths can be paused and respect reduced-motion preferences. The graph
scrolls horizontally on narrow screens and saves its current selection in the URL.

The former `guide/architecture/context` and `guide/architecture/internals` pages
redirect to the main page, retaining supported integration and interaction
selections from both current and legacy query strings.

`tests/architecture-playground.test.mjs` checks all eight integration combinations,
interaction paths, component removal, identity separation, connection/label
geometry, grouped interactions and URL persistence.

## Code map

Open `guide/code-map` for the component diagram. Click a box to highlight its incoming
and outgoing connections and read its responsibilities, process boundary and
source files below the map. Connected-component buttons let you follow a
relationship. The selected component is saved in the URL.

The Portal API boundary contains modules in one Python process per replica. Browser code,
the Sandbox Provider, database and workload processes are shown separately.
OpenShell and Agent Sandbox are examples of the same provider abstraction.
Rows group request/execution code, sandbox management, and state/reconciliation.
Profile data flows into sandbox management. Connection info means the sandbox
identity and provider connector returned by `Store.execution()`; it is not yet
an open stream. State / Metadata storage owns the interface and SQL code; the
Database box represents its backing SQLite file or PostgreSQL service. The
provider and database sit below their callers; the workload sits alongside them.
Terminal I/O & tools includes per-connection input/output/revalidation tasks and
shared command/helper code. Blocking terminal calls use a dedicated bounded
`TerminalIO` thread pool. Maintenance tasks include separate configuration-sync
and controls/namespace-cleanup loops; blocking management work uses
`asyncio.to_thread`. Shared database leases coordinate maintenance across replicas. Integration-specific
workload services are outside the scope of this map. Source paths are relative to this repository root;
runtime source is included in this OSS repository.

`tests/code-map.test.mjs` validates graph endpoints, process membership, source
coverage, connection geometry and selection URL persistence.

## Documentation navigation

Configuration contains separate pages for Profiles, Profile fields, Helm chart
values, Environment variables, Saved state and IDs, and Worked example. Reference
pages share a searchable field component; there is no explorer page or scope-tab
navigation. Helm defaults are explicitly distinguished from deployment overrides
and running release values.

Code map is also a Guide document. Pages share the docs sidebar, breadcrumbs
and previous/next navigation. `/configuration` and `/guide/configuration` redirect
to `/guide/profile-fields`; `/code-map` redirects to `/guide/code-map`. Redirects
retain query parameters and fragments; the landing page uses canonical docs URLs.

Concepts sits beside Get started and introduces terminology with links to deeper
guides.

Database and persistence and Security live under Architecture alongside System
architecture and Code map. Operate covers Deployment checks, Install and upgrade,
Capacity and scaling, and Contributing and releases. The Security guide covers
isolation layers, workload restrictions, identity, sharing and persisted
credentials; its URL remains `/guide/security`.
