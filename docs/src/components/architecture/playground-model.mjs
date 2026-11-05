export const requiredIntegrations = [
  {
    id: "agent-sandbox",
    label: "Agent Sandbox",
    role: "Required",
    icon: "box",
    tone: "core",
    required: true,
  },
];
export const integrations = [
  {
    id: "kata",
    label: "Kata",
    role: "Micro VM isolation",
    icon: "kata",
    tone: "identity",
  },
  {
    id: "omnigent",
    label: "Omnigent",
    role: "UI + host",
    icon: "omnigent",
    tone: "omnigent",
  },
  {
    id: "openshell",
    label: "OpenShell",
    role: "Protected execution",
    icon: "openshell",
    tone: "openshell",
  },
];
export const interactions = [
  { id: "overview", label: "Architecture — no interaction", requires: [] },
  {
    id: "portal-signin",
    label: "User signs in to the sandbox portal",
    requires: [],
  },
  { id: "create", label: "User creates a micro VM", requires: [] },
  {
    id: "internet-access",
    label: "Workload connects to Internet",
    requires: [],
  },
  {
    id: "portal-terminal",
    label: "User opens a portal terminal",
    requires: [],
  },
  {
    id: "omni-signin",
    label: "User signs in to Omnigent",
    requires: ["omnigent"],
  },
  {
    id: "omni-register",
    label: "Omnigent runner registers with server",
    requires: ["omnigent"],
  },
  {
    id: "omni-work",
    label: "User works in a micro VM through Omnigent UI",
    requires: ["omnigent"],
  },
  {
    id: "lifecycle",
    label: "User suspends or resumes a micro VM",
    requires: [],
  },
  {
    id: "profile-update",
    label: "Operator updates a profile through GitOps",
    requires: [],
  },
];
export function groupInteractions(value) {
  const os = value.integrations.includes("openshell");
  return [
    {
      id: "portal",
      label: "Sandbox portal",
      ids: ["portal-signin", "profile-update"],
    },
    {
      id: "native",
      label: os ? "Agent Sandbox + OpenShell" : "Agent Sandbox",
      ids: ["create", "portal-terminal", "internet-access", "lifecycle"],
    },
    {
      id: "omnigent",
      label: "Omnigent",
      ids: ["omni-signin", "omni-register", "omni-work"],
    },
  ].map(({ ids, ...group }) => ({
    ...group,
    items: ids.map((id) => interactions.find((item) => item.id === id)),
  }));
}
export const initialSelection = ["kata", "omnigent"];
export function workloadText(text, selection) {
  if (selection.includes("kata") || typeof text !== "string") return text;
  return text
    .replaceAll("Pod with Kata runtime (MicroVM)", "Pod")
    .replaceAll("Micro VMs", "Pods")
    .replaceAll("micro VMs", "Pods")
    .replaceAll("Micro VM", "Pod")
    .replaceAll("micro VM", "Pod");
}
export function available(interaction, selection) {
  return interaction.requires.every((id) => selection.includes(id));
}
export function normalizePlayground(value = {}) {
  const selected = integrations
    .filter(
      (i) =>
        Array.isArray(value.integrations) && value.integrations.includes(i.id),
    )
    .map((i) => i.id);
  const action = interactions.find((i) => i.id === value.interaction);
  return {
    integrations: selected,
    interaction: action && available(action, selected) ? action.id : "overview",
  };
}
export function readPlayground(search = "") {
  const params = new URLSearchParams(search);
  let selected = [...initialSelection];
  if (params.has("integrations"))
    selected = (params.get("integrations") || "").split(",");
  else if (params.has("workload") || params.has("execution")) {
    selected = [];
    if (["omnigent", "both"].includes(params.get("workload")))
      selected.push("omnigent");
    if (params.get("execution") === "openshell") selected.push("openshell");
  }
  const legacy = {
    auth: "portal-signin",
    create: "create",
    terminal: "portal-terminal",
    lifecycle: "lifecycle",
  };
  return normalizePlayground({
    integrations: selected,
    interaction:
      params.get("interaction") || legacy[params.get("flow")] || "overview",
  });
}
export function playgroundSearch(value) {
  const state = normalizePlayground(value);
  return (
    "?" +
    new URLSearchParams({
      integrations: state.integrations.join(","),
      interaction: state.interaction,
    }).toString()
  );
}

const info = {
  internet: {
    title: "Internet",
    subtitle: "External services / APIs",
    icon: "globe",
    tone: "network",
    where: "Public destinations outside the Kubernetes cluster.",
    identity:
      "Each external service authenticates the workload's tool or API client separately.",
    state:
      "External service state; credentials may be stored in persistent workload files.",
    body: "Workload requests leave through the deployment's allowed egress path. This is outbound access with response traffic, not a public inbound endpoint for the Pod. The Omnigent host tunnel remains a separate, explicitly drawn connection.",
    docs: "/guide/security",
  },
  egress: {
    title: "Cluster egress",
    subtitle: "Routing · CNI",
    icon: "network",
    tone: "network",
    where:
      "Platform networking boundary, not another portal service or a dedicated proxy installed by this application.",
    identity:
      "The enforcing CNI and deployed network policies control permitted destinations; external services still require their own credentials.",
    state:
      "Operator-managed routing, network policy and any deployment-specific NAT/proxy configuration.",
    body: "The direct backend allows cluster DNS plus public IPv4 HTTPS by default, excluding private and link-local ranges. Operators can disable publicHttpsEgress or configure extraEgress. NetworkPolicy requires an enforcing CNI; it does not provide routing or NAT. No Envoy service is integrated by the portal.",
    docs: "/guide/security",
  },
  portalUI: {
    title: "Sandbox portal UI",
    subtitle: "Developer browser",
    icon: "browser",
    tone: "core",
    where: "JavaScript in the developer browser.",
    identity:
      "The portal browser session; the UI does not receive Kubernetes credentials.",
    state: "Browser/UI state, separate from micro VM files and tool login.",
    body: "Creates micro VMs, opens authorized terminals and requests suspend/resume. This browser application is separate from the Omnigent UI.",
    docs: "/guide/getting-started",
  },
  omniUI: {
    title: "Omnigent UI",
    subtitle: "Developer browser",
    icon: "omnigent",
    tone: "omnigent",
    where: "Omnigent web application in the user’s browser.",
    identity:
      "The user signs in to Omnigent independently of the sandbox portal and the micro VM CLI.",
    state: "Omnigent session and UI state.",
    body: "The user chooses an accessible connected host and works through Omnigent. Requests go to the Omnigent web/session API, not through the sandbox portal’s terminal endpoint.",
    docs: "/guide/profiles",
  },
  portal: {
    title: "Sandbox portal",
    subtitle: "API · access · profiles",
    icon: "portal",
    tone: "core",
    where: "Portal application process in its own deployment.",
    identity:
      "Verified portal identity for user requests; scoped Kubernetes identity and, if enabled, gateway client TLS for native operations.",
    state:
      "Admin gates/announcement use the metadata store. Micro VM ownership, sharing and applied profiles still use native retained metadata.",
    body: "Shared management validates identity, grants, profile and resource choices. Its selected native integration owns provisioning, lifecycle and terminal transport.",
    docs: "/guide/architecture#runtime-boundaries",
  },
  metadata: {
    title: "Portal metadata",
    subtitle: "Administrative controls (Postgres/SQLite)",
    icon: "database",
    tone: "storage",
    where:
      "SQLite file mounted into the portal Pod, or a separately provisioned PostgreSQL service.",
    identity:
      "Portal database access, never a direct browser/micro VM connection.",
    state:
      "Global/per-user access gates and administrative announcement. Micro VM inventory is not cut over.",
    body: "Storage is summarized here because its deployment is independent of the integration selection. The current portal requires one replica and Recreate upgrades.",
    docs: "/guide/metadata",
  },
  kubernetes: {
    title: "Kubernetes API",
    subtitle: "Sandbox resources + metadata",
    icon: "kubernetes",
    tone: "core",
    where: "Cluster control plane, separate from the portal process.",
    identity: "Scoped ServiceAccounts, RBAC and operator-installed admission.",
    state:
      "Native Sandbox/Pod/claim records, ownership and retained profile metadata.",
    body: "Direct provisioning uses native resources. With OpenShell, the gateway owns native lifecycle while the portal retains only its permitted metadata/management access.",
    docs: "/guide/deployment",
  },
  controller: {
    title: "Agent Sandbox controller",
    subtitle: "Reconciles native resources",
    icon: "controller",
    tone: "core",
    where: "Separate controller deployment.",
    identity: "Controller ServiceAccount and platform-owned permissions.",
    state: "Desired native workload and claim state.",
    body: "Turns native sandbox state into workload Pods and claims. Scheduling, kubelet and runtime internals are summarized by the micro VM boundary.",
    docs: "/guide/deployment",
  },
  profiles: {
    title: "Profile catalog",
    subtitle: "Deployment-managed config",
    icon: "config",
    tone: "core",
    where:
      "Deployment configuration, mounted/read by the portal; not another server.",
    identity:
      "Operator-owned Helm/GitOps changes. Users can select offered profiles, not rewrite the catalog.",
    state: "Images, commands, helpers and editable resource defaults/ranges.",
    body: "Catalog changes apply to new allocations. Existing micro VMs retain their applied profile. There is no live profile editor in the portal.",
    docs: "/guide/profiles",
  },
  shell: {
    title: "Shells / agent processes",
    subtitle: "Inside the micro VM",
    icon: "terminal",
    tone: "core",
    where:
      "Separate processes inside a container in the Pod with Kata runtime (MicroVM).",
    identity:
      "Workload filesystem identity and the native credentials of invoked tools.",
    state:
      "Process memory and terminals stop on suspension. Only data written to the persistent mount survives.",
    body: "Portal terminals arrive through the selected native integration. An Omnigent host can start agents through its own host tunnel. These are distinct execution paths.",
    docs: "/guide/workspaces",
  },
  volume: {
    title: "Micro VM storage",
    subtitle: "Files · checkpoints · login caches",
    icon: "disk",
    tone: "storage",
    where: "Persistent volume mounted into the Pod’s micro VM.",
    identity: "Workload filesystem identity and platform storage policy.",
    state:
      "Projects and tool credentials written under persistent HOME. Deletion follows native ownership and the storage reclaim policy.",
    body: "Direct Agent Sandbox uses the home claim; protected OpenShell micro VMs use native micro VM storage. Suspension retains files, not process memory.",
    docs: "/guide/workspaces",
  },
  omniServer: {
    title: "Omnigent server",
    subtitle: "Separate deployment",
    icon: "omnigent",
    tone: "omnigent",
    ports: ["Web / session API", "Host-tunnel endpoint"],
    where: "Omnigent server, separately deployed from the portal and sandbox.",
    identity:
      "Browser user identity for UI requests; micro VM host/CLI identity for the host tunnel.",
    state: "Omnigent-owned sessions and connected-host registry.",
    body: "The browser UI connects to its web/session API. The micro VM’s Omnigent host opens an outbound connection to its host-tunnel endpoint. User sign-in does not itself register a sandbox.",
    docs: "/guide/profiles",
  },
  omniHost: {
    title: "Omnigent host",
    subtitle: "Micro VM process",
    icon: "omnigent",
    tone: "omnigent",
    where: "Profile-owned supervised process inside the sandbox workload.",
    identity:
      "The reference startup waits for native micro VM CLI login, then runs omnigent host --server with that login state.",
    state:
      "CLI credentials in persistent HOME; live tunnel/host registration is service-owned runtime state.",
    body: "Connects outbound to Omnigent’s host-tunnel endpoint. Browser work arrives over that existing connection; it does not use the portal’s Kubernetes-exec bridge.",
    docs: "/guide/profiles",
  },
  gateway: {
    title: "OpenShell gateway",
    subtitle: "Native API · client mTLS",
    icon: "openshell",
    tone: "openshell",
    where: "Separate native gateway service/Pod.",
    identity:
      "Portal client TLS bundle authenticates gateway API requests; human authorization stays in the portal.",
    state:
      "Native micro VM records and keys on the gateway’s own data PVC, separate from portal metadata.",
    body: "Owns protected provisioning and execution attachment. Enabling this integration replaces the portal’s direct Kubernetes-exec route; gateway failure never falls back to direct exec.",
    docs: "/guide/security",
  },
  supervisor: {
    title: "OpenShell supervisor",
    subtitle: "Trusted native workload",
    icon: "shield",
    tone: "openshell",
    where: "Separate supervisor workload from the protected sandbox Pod.",
    identity:
      "Gateway-owned trusted execution and operator-installed admission.",
    state:
      "Native runtime/protection state; persistent identities/settings belong to the gateway store.",
    body: "Routes protected commands to the approved Kata workload and checks relayed network requests against policy before opening approved external connections. OpenShell policy, platform admission and CNI are separate enforcement layers. The Omnigent host tunnel is a separate application execution path; its protection must be checked for the actual profile/runtime.",
    docs: "/guide/security",
  },
  idp: {
    title: "Portal identity provider",
    subtitle: "OIDC authorization / validation",
    icon: "key",
    tone: "identity",
    where: "External operator-configured identity provider.",
    identity:
      "Portal authorization-code login with PKCE and validated issuer/audience/claims.",
    state: "Provider identity and the portal’s independent signed session.",
    body: "Shown for the portal sign-in interaction. It does not sign the user in to CAIPE or Omnigent, and it does not establish micro VM CLI credentials.",
    docs: "/guide/security",
  },
  operator: {
    title: "Operator / GitOps",
    subtitle: "Helm / deployment repository",
    icon: "git",
    tone: "core",
    where: "Operator-controlled delivery pipeline, outside the portal UI.",
    identity: "Deployment permissions and review policy.",
    state: "Versioned desired deployment/profile configuration.",
    body: "Changes the profile catalog through the normal deployment workflow. The diagram does not offer a portal profile-edit API.",
    docs: "/guide/deployment",
  },
};
const node = (id, x, y, w, h, extra = {}) => ({
  id,
  x,
  y,
  w,
  h,
  ...info[id],
  ...extra,
});
const edge = (id, from, to, label, points, options = {}) => ({
  id,
  from,
  to,
  label,
  points,
  tone: "core",
  general: true,
  ...options,
});
export function makePlayground(value) {
  const state = normalizePlayground(value),
    has = (id) => state.integrations.includes(id),
    os = has("openshell");
  const signingIn = state.interaction === "portal-signin";
  const nodes = [
    node("portalUI", 45, 45, 175, 100),
    node("portal", 65, 294, 245, 80),
    node("metadata", 65, 415, 245, 75),
    node("kubernetes", 405, 294, 245, 80),
    node("controller", 405, 415, 245, 75),
    node("profiles", 65, 510, 245, 65),
    node("shell", 395, 625, 220, 85),
    node("volume", 65, 625, 245, 85),
    node("internet", 1035, 55, 180, 90),
    node(
      "egress",
      1035,
      415,
      180,
      75,
      os
        ? {
            body: "Protected workload requests use OpenShell's native policy-controlled network path before cluster egress. The portal installs a deny-all direct-egress baseline for protected namespaces; it does not add the direct backend's public-HTTPS grant. Approved binaries/endpoints come from the applied OpenShell policy. Native boundary transport, CNI enforcement and upstream connectivity must be supplied and verified by the deployment. This box summarizes platform networking, not a new proxy service.",
          }
        : {},
    ),
  ];
  const edges = [
    edge(
      "egress-internet",
      "egress",
      "internet",
      "Outbound",
      [
        [1125, 415],
        [1125, 145],
      ],
      { tone: "network", labelAt: [1125, 205] },
    ),
    edge(
      "portal-request",
      "portalUI",
      "portal",
      "API / WS",
      signingIn
        ? [
            [45, 100],
            [15, 100],
            [15, 334],
            [65, 334],
          ]
        : [
            [132, 145],
            [132, 294],
          ],
      signingIn
        ? { labelAt: [15, 280], labelAngle: -90 }
        : { labelAt: [132, 205] },
    ),
    edge(
      "portal-store",
      "portal",
      "metadata",
      "Admin state",
      [
        [188, 374],
        [188, 415],
      ],
      { tone: "storage", labelAt: [188, 395] },
    ),
    edge(
      "profile-read",
      "profiles",
      "portal",
      "Read profiles",
      [
        [310, 550],
        [370, 550],
        [370, 354],
        [310, 354],
      ],
      { labelAt: [370, 450], labelAngle: -90 },
    ),
    edge("native-watch", "kubernetes", "controller", "Reconcile", [
      [528, 374],
      [528, 415],
    ]),
    edge("reconcile-workload", "controller", "shell", "Pods + claims", [
      [528, 490],
      [528, 625],
    ]),
    edge(
      "persistent-files",
      "shell",
      "volume",
      "Files",
      [
        [395, 668],
        [310, 668],
      ],
      { tone: "storage", labelAt: [352, 668] },
    ),
  ];
  if (os) {
    nodes.push(
      node("gateway", 690, 294, 225, 80),
      node("supervisor", 690, 415, 225, 75),
    );
    edges.push(
      edge(
        "protected-network",
        "shell",
        "supervisor",
        "Network requests",
        [
          [615, 690],
          [655, 690],
          [655, 570],
          [860, 570],
          [860, 490],
        ],
        { tone: "openshell", labelAt: [755, 570] },
      ),
      edge(
        "supervisor-egress",
        "supervisor",
        "egress",
        "Policy egress",
        [
          [915, 452],
          [1035, 452],
        ],
        { tone: "openshell", labelAt: [975, 452] },
      ),
      edge(
        "portal-gateway",
        "portal",
        "gateway",
        "API · mTLS",
        [
          [280, 294],
          [280, 275],
          [803, 275],
          [803, 294],
        ],
        { tone: "openshell", labelAt: [590, 275] },
      ),
      edge(
        "gateway-native",
        "gateway",
        "kubernetes",
        "Native lifecycle",
        [
          [690, 334],
          [650, 334],
        ],
        { tone: "openshell" },
      ),
      edge(
        "portal-metadata",
        "portal",
        "kubernetes",
        "Metadata",
        [
          [310, 334],
          [405, 334],
        ],
        { labelAt: [357, 317] },
      ),
      edge(
        "gateway-supervisor",
        "gateway",
        "supervisor",
        "Attach",
        [
          [803, 374],
          [803, 415],
        ],
        { tone: "openshell", labelAt: [803, 395] },
      ),
      edge(
        "protected-exec",
        "supervisor",
        "shell",
        "Commands",
        [
          [803, 490],
          [803, 550],
          [585, 550],
          [585, 625],
        ],
        { tone: "openshell", labelAt: [730, 550] },
      ),
    );
  } else {
    edges.push(
      edge(
        "pod-egress",
        "shell",
        "egress",
        "Allowed traffic",
        [
          [505, 710],
          [505, 745],
          [1060, 745],
          [1060, 490],
        ],
        { tone: "network", labelAt: [805, 745] },
      ),
      edge("portal-native", "portal", "kubernetes", "Native API", [
        [310, 334],
        [405, 334],
      ]),
      edge("direct-exec", "kubernetes", "shell", "pods/exec", [
        [650, 354],
        [675, 354],
        [675, 550],
        [585, 550],
        [585, 625],
      ]),
    );
  }
  if (has("omnigent")) {
    nodes.push(
      node("omniUI", 245, 45, 175, 100),
      node("omniServer", 655, 35, 250, 145),
      node("omniHost", 730, 625, 235, 85),
    );
    const tunnel = [
      [965, 668],
      [1005, 668],
      [1005, 145],
      [905, 145],
    ];
    edges.push(
      edge(
        "omni-browser",
        "omniUI",
        "omniServer",
        "Web API",
        [
          [420, 100],
          [655, 100],
        ],
        { tone: "omnigent", labelAt: [535, 100] },
      ),
      edge("host-tunnel", "omniHost", "omniServer", "Host tunnel", tunnel, {
        tone: "omnigent",
        labelAt: state.interaction === "omni-work" ? null : [1005, 205],
      }),
      edge(
        "omni-commands",
        "omniServer",
        "omniHost",
        "Commands",
        tunnel.slice().reverse(),
        { tone: "omnigent", general: false, labelAt: [1005, 205] },
      ),
      edge(
        "host-process",
        "omniHost",
        "shell",
        "Run agents",
        [
          [730, 670],
          [615, 670],
        ],
        { tone: "omnigent", labelAt: [672, 670] },
      ),
    );
  }
  if (signingIn) {
    nodes.push(node("idp", 45, 180, 290, 60));
    edges.push(
      edge(
        "browser-idp",
        "portalUI",
        "idp",
        "OIDC login",
        [
          [132, 145],
          [132, 180],
        ],
        { tone: "identity", general: false, labelAt: [132, 162] },
      ),
      edge(
        "portal-idp",
        "portal",
        "idp",
        "Validate",
        [
          [220, 294],
          [220, 240],
        ],
        { tone: "identity", general: false, labelAt: [220, 267] },
      ),
    );
  }
  if (state.interaction === "profile-update") {
    nodes.push(node("operator", 450, 165, 175, 75));
    edges.push(
      edge(
        "deploy-profile",
        "operator",
        "profiles",
        "Deploy",
        [
          [450, 202],
          [345, 202],
          [345, 530],
          [310, 530],
        ],
        { general: false, labelAt: [398, 202] },
      ),
    );
  }
  for (const component of nodes) {
    for (const key of [
      "title",
      "subtitle",
      "where",
      "identity",
      "state",
      "body",
    ])
      component[key] = workloadText(component[key], state.integrations);
  }
  if (!has("kata"))
    nodes.find((component) => component.id === "volume").where =
      "Persistent volume mounted into the workload Pod.";
  const native = os ? ["portal-gateway", "gateway-native"] : ["portal-native"];
  const terminal = os
    ? ["portal-gateway", "gateway-supervisor", "protected-exec"]
    : ["portal-native", "direct-exec"];
  const paths = {
    overview: edges.filter((e) => e.general).map((e) => e.id),
    "portal-signin": ["portal-request", "browser-idp", "portal-idp"],
    "internet-access": os
      ? ["protected-network", "supervisor-egress", "egress-internet"]
      : ["pod-egress", "egress-internet"],
    create: [
      "portal-request",
      "portal-store",
      "profile-read",
      ...native,
      "native-watch",
      "reconcile-workload",
      "persistent-files",
    ],
    "portal-terminal": ["portal-request", "portal-store", ...terminal],
    "omni-signin": ["omni-browser"],
    "omni-register": ["host-tunnel"],
    "omni-work": ["omni-browser", "omni-commands", "host-process"],
    lifecycle: [
      "portal-request",
      "portal-store",
      ...native,
      "native-watch",
      "reconcile-workload",
      "persistent-files",
    ],
    "profile-update": ["deploy-profile", "profile-read"],
  };
  return {
    width: 1240,
    height: 800,
    nodes,
    edges,
    state,
    activeEdges: paths[state.interaction],
    groups: [
      {
        id: "browser",
        x: 30,
        y: 15,
        w: has("omnigent") ? 405 : 205,
        h: 145,
        title: "DEVELOPER BROWSER",
      },
      {
        id: "cluster",
        x: 30,
        y: 245,
        w: 1185,
        h: 530,
        title: "Kubernetes Cluster",
        labelOffset: 325,
      },
      {
        id: "workload",
        x: 375,
        y: 590,
        w: 815,
        h: 175,
        title: has("kata") ? "Pod with KATA runtime (MicroVM)" : "Pod",
        kata: has("kata"),
        labelOffset: 280,
      },
    ],
  };
}

export function describeInteraction(value) {
  const { integrations: selected, interaction } = normalizePlayground(value),
    os = selected.includes("openshell");
  const native = os
    ? "The portal calls the OpenShell gateway with client mTLS; the gateway owns native lifecycle."
    : "The portal’s direct adapter submits native resources through the Kubernetes API.";
  const exec = os
    ? "Execution attaches through the OpenShell gateway and supervisor. No direct Kubernetes-exec fallback is used."
    : "The direct adapter verifies the owned Running Pod, then opens Kubernetes exec.";
  const descriptions = {
    "internet-access": {
      summary: os
        ? "Protected workload traffic reaches the Internet through OpenShell policy and the deployment's cluster egress."
        : "Pod traffic reaches the Internet only where namespace policy and cluster networking permit it.",
      steps: os
        ? [
            "A workload process makes a network request under protected OpenShell execution.",
            "The native protected networking path checks the applied policy's allowed binaries and endpoints; direct workload sockets remain denied by the namespace baseline.",
            "The trusted supervisor opens the approved external connection and relays traffic through the protected channel. Platform routing and CNI enforcement remain deployment prerequisites.",
            "Responses return over the established connection. This does not expose a public inbound Pod endpoint.",
          ]
        : [
            "A process in the Pod makes a request; cluster DNS resolution is separately permitted by the namespace baseline.",
            "An enforcing CNI applies the namespace NetworkPolicy. By default the direct backend permits public IPv4 TCP/443, excluding private and link-local ranges; publicHttpsEgress and extraEgress are operator settings.",
            "Platform routing and any required NAT carry permitted traffic to the external destination. NetworkPolicy alone does not establish Internet connectivity.",
            "Responses return over the established connection. Inbound access remains denied by the baseline.",
          ],
      note: "The separate Omnigent host-tunnel connection also needs a permitted route to its configured endpoint. Kata changes compute isolation; it does not grant network access.",
    },
    overview: {
      summary:
        "Structural connections and background services. Choose an interaction to follow a user or operator path.",
      steps: [],
    },
    "portal-signin": {
      summary:
        "Portal authentication establishes access to the sandbox portal only.",
      steps: [
        "The user opens the sandbox portal UI.",
        "The portal redirects the browser through its configured OIDC sign-in flow and validates the authorization result.",
        "A portal session is established. This does not sign the user in to Omnigent or create a host tunnel.",
      ],
    },
    create: {
      summary: "A new micro VM is created from an operator-managed profile.",
      steps: [
        "The portal checks the user, access controls, selected profile, quotas and resource choices.",
        native,
        "Agent Sandbox reconciles Pods and persistent claims; the platform schedules the approved runtime.",
        "Native readiness is reported to the portal. Selected tools run only if the workload image and profile configure them.",
      ],
    },
    "portal-terminal": {
      summary:
        "An authorized portal terminal reaches a shell through the selected native integration.",
      steps: [
        "The browser opens an owner/share-authorized WebSocket to the portal.",
        "The portal selects the allocation’s execution connector.",
        exec,
        "The shell runs inside the sandbox workload. This path is separate from Omnigent UI access.",
      ],
    },
    "omni-signin": {
      summary:
        "The user signs in to the Omnigent web UI independently of sandbox setup.",
      steps: [
        "The browser opens the Omnigent UI and completes the service’s configured sign-in flow.",
        "Omnigent establishes the user’s web/session access.",
        "This does not register the micro VM, start the host process or sign its CLI in. No host-tunnel path is highlighted for this interaction.",
      ],
    },
    "omni-register": {
      summary:
        "The Omnigent runner in the micro VM registers with the configured server.",
      steps: [
        "The profile starts the supervised Omnigent runner/host process in the micro VM.",
        "The reference startup waits for native CLI login state, then runs omnigent host --server for the configured endpoint.",
        "The runner opens an outbound connection to the server’s host-tunnel endpoint and registers as a connected host.",
        "Authorized Omnigent UI users can subsequently select the connected host. Browser sign-in and agent execution are separate interactions.",
      ],
    },
    "omni-work": {
      summary:
        "The user works with an accessible connected micro VM through Omnigent UI.",
      steps: [
        "The user is already signed in to Omnigent and selects an accessible connected host.",
        "UI requests reach Omnigent’s web/session API.",
        "Omnigent routes work over the existing host tunnel to the micro VM host process.",
        "The host starts or controls micro VM agent processes; results return through the same service connection. The sandbox portal terminal bridge is not involved.",
      ],
      note: os
        ? "OpenShell remains part of the selected topology, but the host tunnel is a distinct execution path. Its protection depends on the actual workload/profile/runtime configuration; this view does not imply it passes through the OpenShell gateway."
        : null,
    },
    lifecycle: {
      summary:
        "Manual suspension and resumption retain files while stopping and restarting execution.",
      steps: [
        "The portal authorizes the owner/admin request.",
        native,
        "Native state is reconciled; suspend stops workload execution and resume starts it against the retained volume.",
        "Open terminals and process memory do not survive. Delete is a separate operation that can remove the micro VM claim.",
      ],
    },
    "profile-update": {
      summary:
        "An operator updates desired profile configuration through the deployment workflow.",
      steps: [
        "The operator reviews and changes profile configuration in Helm/GitOps.",
        "The deployment updates the portal’s profile catalog.",
        "New allocations use the updated catalog. Existing micro VMs retain their applied profile; there is no portal profile-edit API.",
      ],
    },
  };
  const description = descriptions[interaction];
  return {
    ...description,
    summary: workloadText(description.summary, selected),
    steps: description.steps.map((step) => workloadText(step, selected)),
    note: workloadText(description.note, selected),
  };
}
