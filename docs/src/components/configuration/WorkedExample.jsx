import React, { useState } from "react";
import CodeBlock from "@theme/CodeBlock";
import { sources } from "./reference.mjs";

const layers = {
  profile: {
    title: "Profile defaults",
    owner: "Profile administrator",
    body: "Image, startup command, terminal, helpers and resource defaults come from the offered profile. Existing sandboxes retain their applied definition.",
  },
  choices: {
    title: "User choices",
    owner: "Engineer",
    body: "The selected request size overrides the starting CPU/memory requests. Both choices remain inside the profile and platform bounds; limits stay 2 CPU / 4 GiB and disk stays 20 GiB.",
  },
  platform: {
    title: "Platform controls",
    owner: "Platform operator",
    body: "The example approves an installed kata-qemu runtime and supplies namespace rules and a resource envelope. The direct backend also injects its non-root Pod baseline; OpenShell uses its native policy and gateway configuration.",
  },
  effective: {
    title: "Effective configuration",
    owner: "Portal resolves; native systems enforce",
    body: "These complete resolved native specs were produced by the actual Python renderer for both backends. They show field injection and resource mapping, rather than a handwritten approximation.",
  },
};

export default function WorkedExample() {
  const [backend, setBackend] = useState("agentSandbox");
  const [size, setSize] = useState("small");
  const [layer, setLayer] = useState("profile");
  const selected = layers[layer];
  const value =
    layer === "profile"
      ? sources.examples[backend]
      : layer === "platform"
        ? sources.examples.platform[backend]
        : sources.examples.native[backend][size];
  return (
    <>
      <h2>From profile to native workload</h2>
      <div className="config-flow" aria-label="Configuration layers">
        {Object.entries(layers).map(([key, item], index) => (
          <React.Fragment key={key}>
            {index > 0 && (
              <span className="flow-plus" aria-hidden="true">
                {index === 3 ? "=" : "+"}
              </span>
            )}
            <button
              className={layer === key ? "flow-step selected" : "flow-step"}
              aria-pressed={layer === key}
              onClick={() => setLayer(key)}
            >
              <small>0{index + 1}</small>
              <strong>{item.title}</strong>
            </button>
          </React.Fragment>
        ))}
      </div>
      <div className="explorer-grid">
        <aside className="detail-panel" aria-live="polite">
          <span className="eyebrow">{selected.owner}</span>
          <h3>{selected.title}</h3>
          <p>{selected.body}</p>
          <label className="size-label" htmlFor="example-backend">
            Example backend
          </label>
          <select
            id="example-backend"
            value={backend}
            onChange={(event) => setBackend(event.target.value)}
          >
            <option value="agentSandbox">Agent Sandbox</option>
            <option value="openShell">OpenShell</option>
          </select>
          <label className="size-label" htmlFor="example-size">
            Example request size
          </label>
          <select
            id="example-size"
            value={size}
            onChange={(event) => {
              setSize(event.target.value);
              setLayer("effective");
            }}
          >
            <option value="small">Small · 500m CPU / 1 GiB</option>
            <option value="medium">Medium · 1 CPU / 2 GiB</option>
          </select>
          <p className="small-note">
            Requests change; limits and disk stay fixed. This creates sample
            configuration, not a live sandbox.
          </p>
        </aside>
        <section className="code-panel" aria-label="Rendered example">
          <CodeBlock
            language="json"
            title={
              layer === "profile"
                ? "Source profile"
                : layer === "platform"
                  ? "Relevant platform values used for this example"
                  : "Full resolved native spec"
            }
            showLineNumbers
          >
            {JSON.stringify(value, null, 2)}
          </CodeBlock>
        </section>
      </div>
      <p className="example-note">
        Examples come from the checked-in default profile and OpenShell example.
        The renderer output is generated and checked alongside the reference.
        These are native specs, not full installation values or running cluster
        resources. Replace placeholder images/connection addresses and install
        an approved runtime before deployment. OpenShell has gateway-managed
        storage and no existing-VM resize support.
      </p>
    </>
  );
}
