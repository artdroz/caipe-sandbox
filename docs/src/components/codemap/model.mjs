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
    job: "Shared Sandbox value returned by the native integrations.",
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
    job: "Select the backend for a profile or retained allocation.",
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
    job: "Profile helper status and execution.",
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
  migrations: {
    path: "apps/portal/portal/storage/migrations/",
    job: "Explicit, versioned schema migrations.",
  },
  runtime: {
    path: "sandbox-images/common-tools/sandbox/runtime.py",
    job: "Engineering-image startup, hooks and supervised services.",
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
    label: "Portal / Controller process",
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
    title: "Portal / Controller",
    subtitle: "One Python process · modules and background tasks",
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
      "The application routes and authentication helpers run inside the Portal / Controller process.",
    symbols: "create_app() · create_sandbox() · terminal() · terminal_target()",
    files: ["app", "auth"],
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
      "Store runs inside the Portal / Controller process. Store.execution() checks access, then obtains an ExecutionTarget from the provider adapter. That object carries the sandbox identity and connector; the stream opens later when connect() invokes the connector. Inventory, ownership, namespace sharing and desired manifests use the metadata database; native state is observed through adapters.",
    symbols: "Store.create() · Store.execution() · Integrations.for_profile()",
    files: ["management", "inventory"],
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
      "Controls, the MetadataStore interface and SQLMetadataStore run inside the Portal / Controller process. Database is the backing data store shown below. Sandbox intent, ownership, sharing and applied profiles live in this database; native resources are observed through adapters. The profile catalog comes from deployment configuration.",
    files: ["controls", "storage", "database", "sql", "migrations"],
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
      "Delegating provisioning and lifecycle operations to the backend.",
      "Verifying the native identity and binding the connector used by an ExecutionTarget.",
    ],
    boundary:
      "The adapters are Python modules inside the portal process. The Sandbox Provider box represents the external backend selected by the profile, such as OpenShell or Agent Sandbox.",
    symbols:
      "Integrations.for_profile() · Integration.create() · Integration.execution()",
    files: ["registry", "direct", "directExec", "protected", "gateway"],
  },
  {
    id: "execution",
    title: "Terminal workers (Execution & tools)",
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
      "All of this code runs inside the Portal / Controller process. Each terminal connection has its own async session tasks; the shell or helper command runs inside the workload Pod/micro VM.",
    symbols:
      "ExecutionTarget · connect() · terminal() · attach_exec() · ToolStatus.status()",
    files: ["app", "terminal", "execution", "helpers", "workspace"],
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
        "This is a task group inside the Portal / Controller process, created for each terminal connection. It is not a separately deployed worker. Blocking native operations are offloaded with asyncio.to_thread; attach_exec also closes connections that finish after the attachment timeout.",
      symbols: "terminal() → output() / input() / revalidate() · attach_exec()",
      worker: {
        kind: "connection-tasks",
        entry: "terminal()",
        tasks: ["output()", "input()", "revalidate()"],
        offload: "asyncio.to_thread",
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
      "The selected external sandbox backend provisions native workloads, owns lifecycle operations and supplies an execution transport.",
    handles: [
      "Creating, finding, updating and deleting native sandbox allocations.",
      "Retaining native ownership, sharing and applied profile information.",
      "Connecting execution to the workload using the backend’s transport.",
    ],
    boundary:
      "One provider abstraction is shown here. A profile selects the concrete backend. Provider services are outside the portal Python process; their portal-side adapters are inside it.",
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
      "Bootstraps the engineering image using the applied profile, persistent HOME and configured startup hooks/services.",
    handles: [
      "Image build contents and the sandbox-start entry point.",
      "Profile-owned startup hooks and supervised service configuration.",
      "Starting the services enabled by the applied profile.",
    ],
    boundary:
      "Runs inside the workload container. Other approved images can have different entry points; not every profile starts these services.",
    symbols: "sandbox-start → sandbox/runtime.py → supervisord",
    files: ["runtime", "images"],
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
    title: "Admin worker",
    subtitle: "Periodic reconciliation task",
    zone: "portal",
    icon: "controller",
    x: 225,
    y: 480,
    w: 200,
    h: 90,
    summary:
      "Reconciles saved manifests, retries administrative enforcement and cleans up eligible empty namespaces through Store.",
    handles: [
      "Starting when administrators are configured or namespacePolicy.deleteWhenEmpty is enabled.",
      "Reconciling persisted access restrictions into native sandbox suspension when administrators are configured.",
      "Running namespace cleanup, logging failures and retrying after a ten-second delay.",
      "Cancelling the background task during application shutdown.",
    ],
    boundary:
      "The lifespan hook starts one conditional asyncio reconciliation loop inside the portal process. It offloads blocking Store operations with asyncio.to_thread. An admin control save also attempts reconciliation immediately; the loop retries afterward. The chart sets WEB_CONCURRENCY=1.",
    symbols:
      "lifespan() → reconcile() · Store.reconcile_controls() · Store.cleanup_namespaces()",
    files: ["app", "management", "chart"],
    worker: {
      kind: "periodic-task",
      entry: "lifespan() → reconcile()",
      delaySeconds: 10,
      condition: "admins or deleteWhenEmpty",
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
      "DatabaseSettings.engine() · SQLMetadataStore.get_controls() · save_controls()",
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
