export const modules = {
  ui: {
    path: "apps/portal/web/main.js",
    job: "Forms, inventory and HTTP requests.",
  },
  socket: {
    path: "apps/portal/web/terminal-connection.js",
    job: "Browser WebSocket connection, readiness and retry handling.",
  },
  app: {
    path: "apps/portal/portal/app.py",
    job: "FastAPI routes, request authorization and terminal stream handling.",
  },
  auth: {
    path: "apps/portal/portal/auth.py",
    job: "Verified identities, sessions and roles.",
  },
  management: {
    path: "apps/portal/portal/sandboxes.py",
    job: "Access checks, quota, creation retries and lifecycle coordination.",
  },
  inventory: {
    path: "apps/portal/portal/inventory.py",
    job: "Sandbox view combining a saved metadata record with native observations.",
  },
  settings: {
    path: "apps/portal/portal/config.py",
    job: "Deployment-owned process settings and runtime/security approval.",
  },
  namespaces: {
    path: "apps/portal/portal/namespaces.py",
    job: "Kubernetes namespace placement, ownership verification and bootstrap.",
  },
  coordination: {
    path: "apps/portal/portal/coordination.py",
    job: "Renewable database leases and ownership checks for native operations.",
  },
  commands: {
    path: "apps/portal/portal/commands.py",
    job: "Shared command arguments, helper IDs and sign-in probe definitions.",
  },
  telemetry: {
    path: "apps/portal/portal/telemetry.py",
    job: "Structured action/request logs and optional OTLP tracing without terminal transcripts.",
  },
  drain: {
    path: "apps/portal/portal/drain.py",
    job: "Mark the portal as draining and budget shutdown time for active terminals.",
  },
  profiles: {
    path: "apps/portal/portal/profiles.py",
    job: "Deployment-owned profiles and retained allocation snapshots.",
  },
  resources: {
    path: "apps/portal/portal/resources.py",
    job: "Allocation values and platform resource policy.",
  },
  bounds: {
    path: "apps/portal/portal/resource_controls.py",
    job: "Editable resource defaults and limits.",
  },
  registry: {
    path: "apps/portal/portal/integrations/__init__.py",
    job: "Register backends, integration status/panels and native dispatch for profiles or saved allocations.",
  },
  openShellProfile: {
    path: "apps/portal/portal/integrations/openshell/profile.py",
    job: "Validate and render the native OpenShell SandboxSpec.",
  },
  openShellPolicy: {
    path: "apps/portal/portal/integrations/openshell/policy.py",
    job: "Revision-checked native policy edits, admission status and saved overrides.",
  },
  networkPolicy: {
    path: "apps/portal/portal/integrations/kubernetes/policy.py",
    job: "Administrator-managed namespace egress policy with native UID/version checks.",
  },
  direct: {
    path: "apps/portal/portal/integrations/agent_sandbox/service.py",
    job: "Native Agent Sandbox creation and lifecycle operations.",
  },
  directExec: {
    path: "apps/portal/portal/integrations/agent_sandbox/execution.py",
    job: "Verify the Pod and supply a Kubernetes-exec connector.",
  },
  protected: {
    path: "apps/portal/portal/integrations/openshell/service.py",
    job: "OpenShell lifecycle and execution-target binding.",
  },
  gateway: {
    path: "apps/portal/portal/integrations/openshell/client.py",
    job: "Gateway RPC and execution transport.",
  },
  execution: {
    path: "apps/portal/portal/execution.py",
    job: "ExecutionTarget and dispatch to its supplied connector.",
  },
  terminal: {
    path: "apps/portal/portal/terminal.py",
    job: "Bounded attachment and cleanup of late exec connections.",
  },
  helpers: {
    path: "apps/portal/portal/tools.py",
    job: "Bounded helper sign-in probes and a short-lived status cache.",
  },
  workspace: {
    path: "apps/portal/portal/workspace.py",
    job: "Bridge file, startup and service operations to the micro VM.",
  },
  controls: {
    path: "apps/portal/portal/controls.py",
    job: "Administrative access gates and announcements.",
  },
  storage: {
    path: "apps/portal/portal/storage/__init__.py",
    job: "Metadata storage interface.",
  },
  sql: {
    path: "apps/portal/portal/storage/sql.py",
    job: "SQLite/PostgreSQL storage implementation.",
  },
  schema: {
    path: "apps/portal/portal/storage/schema.py",
    job: "SQLAlchemy table definitions for sandbox intent, grants, controls, requests and leases.",
  },
  schemaCommand: {
    path: "apps/portal/portal/storage/__main__.py",
    job: "Explicit migrate/check commands for init containers and operators.",
  },
  migrations: {
    path: "apps/portal/portal/storage/migrations/",
    job: "Explicit, versioned schema migrations.",
  },
  runtime: {
    path: "sandbox-images/common-tools/sandbox/runtime.py",
    job: "Startup hooks and supervised services for images that include common tools.",
  },
  runtimeConfig: {
    path: "sandbox-images/common-tools/sandbox/configuration.py",
    job: "Validate and manage guest startup/service configuration files.",
  },
  chart: {
    path: "charts/caipe-sandbox/",
    job: "Portal deployment, configuration, permissions and storage settings.",
  },
  examples: {
    path: "apps/portal/examples/",
    job: "Example profiles and deployment values.",
  },
  images: {
    path: "sandbox-images/",
    job: "Workload image recipes and their shared startup/service tools.",
  },
  database: {
    path: "apps/portal/portal/storage/database.py",
    job: "Database URL validation and bounded SQLite/PostgreSQL connections.",
  },
};

export const zones = {
  browser: {
    label: "Developer browser",
    icon: "browser",
  },
  portal: {
    label: "Portal API process",
    icon: "portal",
  },
  native: {
    label: "External Sandbox Provider",
    icon: "kubernetes",
  },
  microvm: {
    label: "Workload Pod / micro VM",
    icon: "terminal",
  },
  persistence: {
    label: "Persistent data",
    icon: "database",
  },
};

export const groups = [
  {
    id: "portal",
    x: 205,
    y: 25,
    w: 720,
    h: 570,
    title: "Portal API",
    subtitle: "One process per replica · modules and background tasks",
  },
  {
    id: "native",
    x: 685,
    y: 615,
    w: 240,
    h: 155,
    title: "SANDBOX BACKEND",
    subtitle: "Selected by the profile",
  },
  {
    id: "microvm",
    x: 970,
    y: 25,
    w: 250,
    h: 390,
    title: "POD / MICRO VM",
    subtitle: "Image and profile-owned processes",
  },
];

export const lanes = [
  {
    title: "Requests & execution",
    x: 225,
    y: 85,
  },
  {
    title: "Sandbox management",
    x: 225,
    y: 275,
  },
  {
    title: "State & reconciliation",
    x: 225,
    y: 465,
  },
];

export const components = [
  {
    id: "browser",
    title: "Browser UI",
    subtitle: "Portal web app",
    zone: "browser",
    icon: "browser",
    x: 20,
    y: 100,
    w: 150,
    h: 90,
    summary:
      "Renders the sandbox portal and sends HTTP requests and terminal WebSocket traffic to the API.",
    handles: [
      "Profile and resource selection, inventory and lifecycle controls.",
      "Browser terminal connection state and rendering.",
    ],
    boundary:
      "JavaScript in the browser. It does not receive Kubernetes credentials or talk directly to native services.",
    files: ["ui", "socket"],
  },
  {
    id: "routes",
    title: "Routes & identity",
    subtitle: "HTTP / WebSocket entry points",
    zone: "portal",
    icon: "key",
    x: 225,
    y: 100,
    w: 200,
    h: 90,
    summary:
      "Owns the application entry points. Validates origin and user identity, then delegates to management or execution code.",
    handles: [
      "Application startup, dependency wiring and API routes.",
      "OIDC/session identity, roles and request checks.",
      "Terminal WebSocket handling and calling the execution bridge.",
    ],
    boundary:
      "Routes, authentication and telemetry run inside each portal API process. Chart deployment uses one application worker per Pod; PostgreSQL-backed replicas are separate Pods.",
    symbols: "create_app() · create_sandbox() · terminal() · terminal_target()",
    files: ["app", "auth", "settings", "telemetry", "drain"],
  },
  {
    id: "store",
    title: "Sandbox management",
    subtitle: "Store · access, quota, lifecycle",
    zone: "portal",
    icon: "controller",
    x: 465,
    y: 290,
    w: 200,
    h: 90,
    summary:
      "Coordinates sandbox inventory, access checks and lifecycle operations. Uses profile data for allocation, and returns provider-supplied connection information for terminals and helpers.",
    handles: [
      "Ownership and sharing checks, administrative access gates and quota.",
      "Creation request IDs, retry recovery and profile/resource validation.",
      "Selecting the profile’s backend for creation, or the retained backend for existing allocations.",
      "Checking sandbox access and returning connection info: sandbox identity, a provider connector and an optional default command.",
    ],
    boundary:
      "Store runs inside the portal API process. Store.execution() checks access, then obtains an ExecutionTarget carrying native identity and a connector; the stream opens later. Metadata reservations, revisions and renewable leases coordinate operations across replicas. Native calls are not part of the database transaction.",
    symbols: "Store.create() · Store.execution() · Integrations.for_profile()",
    files: ["management", "inventory", "namespaces", "coordination"],
  },
  {
    id: "profiles",
    title: "Profiles & resources",
    subtitle: "Catalog, sizing, bounds",
    zone: "portal",
    icon: "config",
    x: 225,
    y: 290,
    w: 200,
    h: 90,
    summary:
      "Reads the operator-managed catalog and interprets the image, commands, helpers and permitted resource choices for each profile.",
    handles: [
      "Profile selection and revision validation.",
      "Default sizes, editable ranges and platform resource limits.",
      "Deployment-supplied profile configuration and examples.",
    ],
    boundary:
      "The catalog is deployment configuration, not a service or a table in the portal metadata database. Existing allocations retain their applied profile.",
    symbols: "Profiles.get() · Profiles.size() · Profiles.validate_size()",
    files: ["profiles", "resources", "bounds", "chart", "examples"],
  },
  {
    id: "metadata",
    title: "State / Metadata storage",
    subtitle: "Storage API & SQL adapter",
    zone: "portal",
    icon: "database",
    x: 465,
    y: 480,
    w: 200,
    h: 90,
    summary:
      "Provides the portal metadata storage interface and its SQLite/PostgreSQL implementation. The application uses it for sandbox intent, operation coordination, namespace grants and administrative controls.",
    handles: [
      "Reading and saving global/per-user access policy and announcements through Controls.",
      "Validating stored policy, checking revisions and reporting conflicting writes.",
      "Database selection, bounded connections, schema checks and versioned migrations.",
      "Persisting sandbox manifests, native bindings, namespace grants, operation journals and coordination leases.",
    ],
    boundary:
      "Controls, MetadataStore and SQLMetadataStore run inside the portal API process. Schema definitions and Alembic revisions are checked into the repository. The backing database stores saved intent and coordination, not every transient runtime status or workload file. Normal application startup checks the schema; the chart's init container migrates only for Recreate.",
    files: [
      "controls",
      "storage",
      "database",
      "sql",
      "schema",
      "schemaCommand",
      "migrations",
    ],
    symbols: "Controls.read() / save() → MetadataStore → SQLMetadataStore",
  },
  {
    id: "adapters",
    title: "Provider adapters",
    subtitle: "Lifecycle & execution bindings",
    zone: "portal",
    icon: "network",
    x: 705,
    y: 290,
    w: 200,
    h: 90,
    summary:
      "Selects the configured sandbox backend and delegates lifecycle and execution operations through its adapter.",
    handles: [
      "Selecting a backend from the profile or retained allocation.",
      "Delegating native lifecycle, supported reconciliation and Network & security panels.",
      "Verifying the native identity and binding the connector used by an ExecutionTarget.",
    ],
    boundary:
      "The adapters are Python modules inside the portal process. The Sandbox Provider box represents the external backend selected by the profile, such as OpenShell or Agent Sandbox.",
    symbols:
      "Integrations.for_profile() · Integration.create() · Integration.execution()",
    files: [
      "registry",
      "direct",
      "directExec",
      "protected",
      "gateway",
      "openShellProfile",
      "openShellPolicy",
      "networkPolicy",
    ],
  },
  {
    id: "execution",
    title: "Terminal I/O & tools",
    subtitle: "Terminal sessions · commands · helpers · files",
    zone: "portal",
    icon: "terminal",
    x: 465,
    y: 100,
    w: 440,
    h: 90,
    summary:
      "Handles terminal sessions and shared command, helper and file operations using the sandbox connection information supplied by sandbox management.",
    handles: [
      "Opening a command stream through the provider-supplied connector.",
      "Managing terminal WebSocket sessions, including input/output, resizing, access rechecks and cleanup.",
      "Helper status/execution and file/startup/service operations.",
      "Caching helper status and probing helpers through a bounded ThreadPoolExecutor (up to eight concurrent probes).",
    ],
    boundary:
      "Code runs in the portal API process, not separate worker Pods. Each terminal has async tasks; blocking terminal calls use a dedicated bounded TerminalIO thread pool, separate from management offloads. Actual commands run in the workload.",
    symbols:
      "ExecutionTarget · connect() · terminal() · attach_exec() · ToolStatus.status()",
    files: ["app", "terminal", "execution", "helpers", "workspace", "commands"],
    terminalWorker: {
      summary:
        "Runs the input, output and access-revalidation tasks for each authorized terminal WebSocket connection.",
      handles: [
        "Receiving sandbox identity and a provider connector from sandbox management after access checks.",
        "Selecting the terminal/helper command from the applied profile and attaching with a timeout.",
        "Relaying terminal output, stdin and resize messages.",
        "Rechecking terminal access while the connection is open.",
        "Cancelling sibling tasks and closing the connection on completion, disconnect or failure.",
      ],
      boundary:
        "Per-connection asyncio tasks run inside each portal process. Attach, I/O and resize calls use TerminalIO.run() and its semaphore/bounded ThreadPoolExecutor (settings.terminalIoWorkers, default 32). attach_exec closes late connections after timeout. Management calls keep their own asyncio.to_thread path.",
      symbols: "terminal() → output() / input() / revalidate() · attach_exec()",
      worker: {
        kind: "connection-tasks",
        entry: "terminal()",
        tasks: ["output()", "input()", "revalidate()"],
        offload: "TerminalIO.run",
        concurrencySetting: "settings.terminalIoWorkers",
      },
      files: ["app", "terminal", "execution"],
    },
  },
  {
    id: "sandbox-provider",
    title: "Sandbox Provider",
    subtitle: "OpenShell · Agent Sandbox",
    zone: "native",
    icon: "kubernetes",
    x: 705,
    y: 660,
    w: 200,
    h: 95,
    summary:
      "Represents the selected native stack, rather than a single service: Kubernetes API/controller for direct Agent Sandbox, or OpenShell gateway/supervisor and its compute dependencies.",
    handles: [
      "Creating, finding, updating and deleting native sandbox allocations.",
      "Maintaining native objects and backend-owned state. Portal ownership, sharing and applied profile snapshots remain in the portal database.",
      "Direct terminals use Kubernetes exec; OpenShell terminals use its authenticated gateway/supervisor path.",
    ],
    boundary:
      "The box summarizes a backend boundary, not one Pod or daemon. Agent Sandbox's controller manages resources; direct exec goes through the Kubernetes API. OpenShell supplies its own attachment path without direct-exec fallback. All portal-side adapters stay inside the portal process.",
    files: [],
    external:
      "OpenShell and Agent Sandbox are example implementations. Their native services and Kubernetes dependencies are owned outside this portal application.",
  },
  {
    id: "startup",
    title: "Image startup",
    subtitle: "Hooks & supervised services",
    zone: "microvm",
    icon: "play",
    x: 990,
    y: 100,
    w: 210,
    h: 90,
    summary:
      "Bootstraps images that include common tools, using persistent HOME and configured startup hooks/services. Other images can use a different entry point.",
    handles: [
      "Image build contents and the sandbox-start entry point.",
      "Image-provided initial setup and guest-configured startup hooks/services.",
      "Starting enabled services from the workload's persisted configuration.",
    ],
    boundary:
      "Runs inside the workload container. Other approved images can have different entry points; not every profile starts these services.",
    symbols: "sandbox-start → sandbox/runtime.py → supervisord",
    files: ["runtime", "runtimeConfig", "images"],
  },
  {
    id: "tools",
    title: "Shells, helpers & agents",
    subtitle: "Processes inside the workload",
    zone: "microvm",
    icon: "terminal",
    x: 990,
    y: 290,
    w: 210,
    h: 90,
    summary:
      "Runs the profile’s terminal command, helper scripts and agent processes against the mounted filesystem.",
    handles: [
      "Terminal commands and helper scripts reached through portal execution.",
      "Agent processes and background services enabled by the workload image/profile.",
      "Files and tool credentials written to persistent storage.",
    ],
    boundary:
      "Workload processes, not portal modules. Process memory and open terminals stop on suspension; persisted files can survive.",
    files: [],
    external:
      "Commands and tools come from the selected workload image and profile. They do not all share one implementation in this repository.",
  },
  {
    id: "admin-worker",
    title: "Maintenance tasks",
    subtitle: "Configuration · controls · cleanup",
    zone: "portal",
    icon: "controller",
    x: 225,
    y: 480,
    w: 200,
    h: 90,
    summary:
      "Runs configuration reconciliation and separate administrative/namespace maintenance loops through Store.",
    handles: [
      "Checking supported native saved intent at settings.reconcileIntervalSeconds (default 30; 0 disables it), with database-coordinated claims across replicas.",
      "Reconciling persisted access restrictions into native sandbox suspension when administrators are configured.",
      "Running the separate controls/namespace-cleanup loop when admins or deleteWhenEmpty are configured, with a ten-second delay.",
      "Cancelling the background task during application shutdown.",
    ],
    boundary:
      "Lifespan starts distinct asyncio loops in each portal process; blocking maintenance work uses asyncio.to_thread. Shared leases prevent concurrent ownership of the same reconciliation work. Automatic configuration sync currently supports direct Agent Sandbox; OpenShell exposes native drift/policy operations without a general reconcile method.",
    symbols:
      "lifespan() → reconcile_resources() / reconcile() → Store + database claims",
    files: ["app", "management", "coordination", "chart"],
    worker: {
      kind: "periodic-tasks",
      entry: "lifespan()",
      loops: [
        {
          entry: "reconcile_resources()",
          intervalSetting: "settings.reconcileIntervalSeconds",
          defaultSeconds: 30,
          condition: "non-zero interval",
        },
        {
          entry: "reconcile()",
          delaySeconds: 10,
          condition: "admins or deleteWhenEmpty",
        },
      ],
      offload: "asyncio.to_thread",
    },
  },
  {
    id: "database",
    title: "Database",
    subtitle: "SQLite / PostgreSQL",
    zone: "persistence",
    icon: "database",
    x: 465,
    y: 660,
    w: 200,
    h: 95,
    summary:
      "Persists sandbox intent, namespace access, lifecycle coordination, administrative policy and announcements.",
    handles: [
      "Durable sandbox records, namespace grants, operation journals, global/per-user controls and announcements.",
      "Revision-checked writes and schema compatibility checks.",
      "SQLite or PostgreSQL connections with bounded pools and explicit migrations.",
    ],
    boundary:
      "This box represents stored data, not another portal worker. SQLite is a file mounted into the portal Pod; PostgreSQL is a separately provisioned database service. The SQL adapter code runs inside the portal process. Sandbox inventory and sharing use this database; the offered profile catalog remains deployment configuration.",
    symbols:
      "DatabaseSettings.engine() · SQLMetadataStore.reserve_create() · confirm_binding() · check_schema()",
    files: [],
    sourceHeading: "Backing store",
    external:
      "SQLite uses a file mounted into the portal Pod; PostgreSQL uses a separately provisioned database service. The State / Metadata storage component owns the SQL adapter, schema checks and migrations.",
  },
];

export const connections = [
  {
    id: "requests",
    from: "browser",
    to: "routes",
    label: "HTTP/WS",
    points: [
      [170, 145],
      [225, 145],
    ],
    labelAt: [197, 125],
    angle: 0,
  },
  {
    id: "dispatch",
    from: "routes",
    to: "store",
    label: "Dispatch",
    points: [
      [325, 190],
      [325, 245],
      [525, 245],
      [525, 290],
    ],
    labelAt: [425, 245],
    angle: 0,
  },
  {
    id: "execution-request",
    from: "routes",
    to: "execution",
    label: "HTTP/WS",
    points: [
      [425, 145],
      [465, 145],
    ],
    labelAt: [445, 145],
    angle: -90,
  },
  {
    id: "profile",
    from: "profiles",
    to: "store",
    label: "Profile data",
    points: [
      [425, 335],
      [465, 335],
    ],
    labelAt: [445, 335],
    angle: -90,
  },
  {
    id: "backend",
    from: "store",
    to: "adapters",
    label: "Backend",
    points: [
      [665, 335],
      [705, 335],
    ],
    labelAt: [685, 350],
    angle: -90,
  },
  {
    id: "target",
    from: "store",
    to: "execution",
    label: "Connection info",
    points: [
      [610, 290],
      [610, 190],
    ],
    labelAt: [610, 240],
    angle: 0,
  },
  {
    id: "connector",
    from: "execution",
    to: "adapters",
    label: "Connect",
    points: [
      [805, 190],
      [805, 290],
    ],
    labelAt: [805, 240],
    angle: 0,
  },
  {
    id: "reconcile",
    from: "admin-worker",
    to: "store",
    label: "Reconcile",
    points: [
      [425, 525],
      [445, 525],
      [445, 405],
      [485, 405],
      [485, 380],
    ],
    labelAt: [445, 450],
    angle: -90,
  },
  {
    id: "gates",
    from: "store",
    to: "metadata",
    label: "Read / write",
    bidirectional: true,
    points: [
      [565, 380],
      [565, 480],
    ],
    labelAt: [565, 430],
    angle: 0,
  },
  {
    id: "provider",
    from: "adapters",
    to: "sandbox-provider",
    label: "Lifecycle / exec",
    points: [
      [805, 380],
      [805, 660],
    ],
    labelAt: [805, 525],
    angle: 0,
  },
  {
    id: "database",
    from: "metadata",
    to: "database",
    label: "Read / write · SQL",
    bidirectional: true,
    points: [
      [565, 570],
      [565, 660],
    ],
    labelAt: [565, 615],
    angle: 0,
  },
  {
    id: "workload",
    from: "sandbox-provider",
    to: "tools",
    label: "Provision / exec",
    points: [
      [905, 710],
      [950, 710],
      [950, 335],
      [990, 335],
    ],
    labelAt: [950, 535],
    angle: -90,
  },
  {
    id: "start",
    from: "startup",
    to: "tools",
    label: "Start processes",
    points: [
      [1095, 190],
      [1095, 290],
    ],
    labelAt: [1095, 240],
    angle: 0,
  },
];
export function normalizeCodeMap(value = {}) {
  const aliases = {
    "terminal-worker": "execution",
    "agent-sandbox": "sandbox-provider",
    openshell: "sandbox-provider",
    "runtime-provider": "sandbox-provider",
  };
  const component = aliases[value.component] || value.component;
  return {
    component: components.some((item) => item.id === component)
      ? component
      : "store",
  };
}
export function readCodeMap(search = "") {
  return normalizeCodeMap(Object.fromEntries(new URLSearchParams(search)));
}
export function codeMapSearch(value) {
  return "?" + new URLSearchParams(normalizeCodeMap(value)).toString();
}
export function makeCodeMap(value = {}) {
  return {
    width: 1245,
    height: 785,
    groups,
    lanes,
    components,
    connections,
    state: normalizeCodeMap(value),
  };
}
