# Documentation site

This Docusaurus 3 site accompanies the CAIPE Sandbox portal, workload tools and
Helm charts. It preserves the configuration explorer, code map and architecture
playground; the old evaluation site is not included.

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
check Guide navigation, configuration tabs and sizing, code-map selections,
slide buttons and arrow keys, dark mode, and a narrow/mobile viewport.

Production builds generate their registry and route metadata in
`.docusaurus-build/`; the live development server uses `.docusaurus/`. This keeps
`npm run build` from replacing the preview’s generated modules during development.

If a browser retains a missing-chunk error after a server restart, reload the
page. To reset development metadata, stop the preview, run `npm run clear`, and
start it again with the command above.

## Structure

- `content/`: Markdown and MDX guides, ordered by `sidebars.js`.
- `src/pages/`: home, configuration, code map and slides.
- `src/components/`: interactive documentation components.
- `src/css/custom.css`: shared styling and responsive layouts.
- `static/img/`: local branding assets.
- `docusaurus.config.js`: navigation and site settings.

The site accompanies the portal, charts and workload tools included in this repository.
Example configuration uses placeholders; see the packaging guide for installation.

Nothing in `npm start`, `npm run build`, or `npm run serve` publishes the site.
For a future subpath deployment, set `DOCS_BASE_URL=/caipe-sandbox/` when building.
The configured GitHub Pages origin is a future hosting target, not a live-site claim.

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

The Portal / Controller boundary contains modules in one Python process. Browser code,
the Sandbox Provider, database and workload processes are shown separately.
OpenShell and Agent Sandbox are examples of the same provider abstraction.
Rows group request/execution code, sandbox management, and state/reconciliation.
Profile data flows into sandbox management. Connection info means the sandbox
identity and provider connector returned by `Store.execution()`; it is not yet
an open stream. State / Metadata storage owns the interface and SQL code; the
Database box represents its backing SQLite file or PostgreSQL service. The
provider and database sit below their callers; the workload sits alongside them.
Terminal workers (Execution & tools) includes terminal sessions and shared command/helper code.
Its details explain the terminal worker’s per-connection input/output/revalidation
tasks. Admin worker means the conditional lifespan reconciliation task. Both run inside the portal
process and offload blocking calls with `asyncio.to_thread`. Integration-specific
workload services are outside the scope of this map. Source paths are relative to this repository root;
runtime source is included in this OSS repository.

`tests/code-map.test.mjs` validates graph endpoints, process membership, source
coverage, connection geometry and selection URL persistence.

## Documentation navigation

Code map, Configuration explorer and Slides are regular Guide documents. They
share the docs sidebar, breadcrumbs and previous/next navigation. The former
`/code-map`, `/configuration` and `/slides` URLs redirect into `/guide/`, retaining
query parameters and fragments. The landing page links to the canonical docs URLs.

Concepts sits beside Get started near the top of the sidebar. Lifecycle,
Profiles and Configuration explorer are direct entries; there is no separate
Use the portal category. Concepts introduces terminology and links to the deeper
guides rather than repeating their configuration and operational instructions.

Security lives under Architecture alongside System architecture and Code map.
It covers isolation layers, workload restrictions, identity, sharing and persisted
credentials. Its URL remains `/guide/security`.
