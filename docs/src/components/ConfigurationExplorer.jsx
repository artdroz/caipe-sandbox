import React, { useState } from "react";
import CodeBlock from "@theme/CodeBlock";
import Link from "@docusaurus/Link";

const topics = {
  profile: {
    title: "Profile",
    owner: "Profile administrator",
    body: "The catalog defines image, startup, terminal and helpers. Resource bounds narrow the platform envelope. Changing a catalog entry does not rewrite an existing micro VM.",
    fields: [
      "agentSandbox.spec",
      "terminal.command",
      "helpers",
      "ui.resources",
    ],
  },
  developer: {
    title: "Developer choices",
    owner: "Micro VM owner",
    body: "Choose an offered profile, display name and resource sizes within permitted bounds. The API validates requests independently of browser controls.",
    fields: [
      "Display name",
      "Profile selection",
      "CPU and memory",
      "Micro VM size at creation",
    ],
  },
  platform: {
    title: "Platform controls",
    owner: "Platform operator",
    body: "The deployment supplies allowed runtimes, resource policy, placement and storage. Admission and network enforcement must be installed and validated separately.",
    fields: [
      "settings.runtimeClass",
      "settings.allowedRuntimeClasses",
      "resourcePolicy",
      "namespace",
    ],
  },
  effective: {
    title: "Effective fields",
    owner: "Portal resolves; native systems enforce",
    body: "Selected resources become native container and claim fields. Kubernetes does not interpret ui.resources. Helpers and terminal commands stay portal metadata.",
    fields: [
      "containers[0].resources",
      "volumeClaimTemplates",
      "runtimeClassName",
      "Persistent mount",
    ],
  },
};
const sizes = {
  small: { cpu: "500m", memory: "1Gi" },
  medium: { cpu: "1", memory: "2Gi" },
};
const profile = `profiles:
  - id: engineering
    title: Engineering micro VM
    agentSandbox:
      spec:
        podTemplate:
          spec:
            containers:
              - name: host
                image: example.invalid/approved-tools:reviewed
                command: [sleep, infinity]
                workingDir: /home/sandbox
                env:
                  - name: HOME
                    value: /home/sandbox
                volumeMounts:
                  - name: home
                    mountPath: /home/sandbox
    terminal:
      command: [/bin/sh, -i]
    helpers:
      - id: micro-vm
        title: Open micro VM
        icon: folder
        script: cd "$HOME" && exec /bin/sh -i
    ui:
      resources:
        default:
          requests: {cpu: 500m, memory: 1Gi}
          limits: {cpu: "2", memory: 4Gi}
          storage: 20Gi
        minimum:
          requests: {cpu: 100m, memory: 256Mi}
          limits: {cpu: 100m, memory: 256Mi}
          storage: 1Gi
        maximum:
          requests: {cpu: "2", memory: 4Gi}
          limits: {cpu: "2", memory: 4Gi}
          storage: 50Gi`;
const platform = `# Relevant placement/runtime fragment, not full deployment values.
settings:
  runtimeClass: kata-qemu
  allowedRuntimeClasses: [kata-qemu]
namespace:
  strategy: perSandbox
defaultProfile: engineering
# Install runtime, storage, admission and network controls separately.
# Set the deployment resourcePolicy envelope before opening access.`;

export default function ConfigurationExplorer() {
  const [topic, setTopic] = useState("profile");
  const [size, setSize] = useState("small");
  const [view, setView] = useState("profile");
  const selected = topics[topic],
    resource = sizes[size];
  const effective = `# Illustrative native field mapping, not a full manifest.
spec:
  podTemplate:
    spec:
      runtimeClassName: kata-qemu
      containers:
        - name: host
          resources:
            requests: {cpu: "${resource.cpu}", memory: ${resource.memory}}
            limits: {cpu: "2", memory: 4Gi}
  volumeClaimTemplates:
    - metadata:
        name: home
      spec:
        resources:
          requests:
            storage: 20Gi`;
  return (
    <>
      <p className="eyebrow">INTERACTIVE REFERENCE / CONFIGURATION</p>
      <h1>Configuration explorer</h1>
      <p className="page-lead">
        Inspect configuration ownership and how resource choices map to native
        micro VM fields.
      </p>
      <div className="config-flow" aria-label="Configuration layers">
        {Object.entries(topics).map(([key, t], i) => (
          <React.Fragment key={key}>
            {i > 0 && (
              <span className="flow-plus" aria-hidden="true">
                {i === 3 ? "=" : "+"}
              </span>
            )}
            <button
              className={topic === key ? "flow-step selected" : "flow-step"}
              aria-pressed={topic === key}
              onClick={() => {
                setTopic(key);
                if (key === "platform") setView("platform");
                else if (key === "effective" || key === "developer")
                  setView("effective");
                else setView("profile");
              }}
            >
              <small>0{i + 1}</small>
              <strong>{t.title}</strong>
            </button>
          </React.Fragment>
        ))}
      </div>
      <div className="explorer-grid">
        <aside className="detail-panel" aria-live="polite">
          <span className="eyebrow">{selected.owner}</span>
          <h2>{selected.title}</h2>
          <p>{selected.body}</p>
          <ul className="field-list">
            {selected.fields.map((f) => (
              <li key={f}>
                <code>{f}</code>
              </li>
            ))}
          </ul>
          <label className="size-label" htmlFor="size-choice">
            Example request size
          </label>
          <select
            id="size-choice"
            value={size}
            onChange={(e) => {
              setSize(e.target.value);
              setTopic("effective");
              setView("effective");
            }}
          >
            <option value="small">Small · 500m CPU / 1 GiB</option>
            <option value="medium">Medium · 1 CPU / 2 GiB</option>
          </select>
          <p className="small-note">
            Limits stay at 2 CPU / 4 GiB; storage stays at 20 GiB. This example
            changes resource requests only.
          </p>
          <Link to="/guide/profiles">Read the profile guide →</Link>
        </aside>
        <section className="code-panel" aria-label="Configuration example">
          <div
            className="segmented"
            role="group"
            aria-label="Configuration view"
          >
            {[
              ["profile", "Profile YAML"],
              ["platform", "Platform values"],
              ["effective", "Effective fields"],
            ].map(([k, label]) => (
              <button
                key={k}
                aria-pressed={view === k}
                onClick={() => setView(k)}
              >
                {label}
              </button>
            ))}
          </div>
          <CodeBlock
            language="yaml"
            title={
              view === "effective"
                ? "Native field mapping"
                : view === "platform"
                  ? "Platform values fragment"
                  : "Illustrative engineering profile"
            }
            showLineNumbers
          >
            {view === "profile"
              ? profile
              : view === "platform"
                ? platform
                : effective}
          </CodeBlock>
        </section>
      </div>
      <p className="example-note">
        These are illustrative snippets, not output from a running renderer or a
        complete installation. Replace the example image and verify the
        installed runtime and storage configuration. OpenShell has its own
        native profile and policy shape.
      </p>
    </>
  );
}
