import React, { useState } from "react";
import CodeBlock from "@theme/CodeBlock";
import Link from "@docusaurus/Link";
import {
  groups,
  scopes,
  searchEntries,
  sources,
  systems,
} from "./reference.mjs";

const sourceFiles = {
  profile:
    "portal/profiles.py · portal/commands.py · portal/resource_controls.py",
  deployment: "charts/caipe-sandbox/values.yaml · values.schema.json",
  state:
    "portal/storage/__init__.py · portal/controls.py · runtime integrations",
  environment: "portal/config.py · chart templates",
};
const nativeFields = {
  "agentSandbox.spec": [
    [
      "podTemplate.spec.containers[0].image / command / args / env / workingDir",
      "Profile-defined program setup. Image must supply its tools and startup process; workingDir does not make a path persistent.",
    ],
    [
      "podTemplate.spec.containers[0].volumeMounts / volumeClaimTemplates",
      "Mount the home claim at the persistent path. One claim named home is supported. Storage size/class are resolved by the portal.",
    ],
    [
      "podTemplate.spec.initContainers / volumes",
      "Supported initialization and mounts, subject to allocation/security checks and cluster admission. Host paths and projected API tokens are rejected.",
    ],
    [
      "podTemplate.spec.nodeSelector / affinity / tolerations",
      "Native workload placement, distinct from top-level chart placement of the portal Pod.",
    ],
    [
      "podTemplate.spec.runtimeClassName",
      "May select an approved runtime; omitted uses settings.runtimeClass. Installed Kata must be selected to provide a micro VM boundary.",
    ],
    [
      "podTemplate.spec.securityContext / serviceAccountName / automountServiceAccountToken",
      "Platform-owned identity and baseline. Conflicting values are rejected; token automount and host namespaces are disabled.",
    ],
    [
      "containers[0].resources / volumeClaimTemplates[0].spec.resources",
      "Resolved CPU/memory and disk choices. With ui.resources, duplicating CPU/memory or claim-storage defaults in this native spec is rejected.",
    ],
    [
      "operatingMode / shutdownPolicy",
      "Portal-managed lifecycle: initially Running with Retain. Later lifecycle operations update supported native state.",
    ],
  ],
  "openShell.spec": [
    [
      "template.image / command / environment",
      "Native OpenShell workload image, startup argument vector and environment. Not Kubernetes containers[].",
    ],
    [
      "template.resources / template.runtime_class_name",
      "Portal-resolved CPU/memory and deployment-approved runtime. Disk comes from gateway configuration; current portal integration cannot resize an existing VM.",
    ],
    ["policy.version", "Supported native policy version is 1."],
    [
      "policy.filesystem / policy.landlock / policy.process",
      "Starting native protection. Supported creation overrides become saved configuration. These settings are set at provision time.",
    ],
    [
      "policy.network_policies / policy.network_middlewares",
      "Supported live network edits through Network & security. Owner/admin edits override the starting profile and survive sync; native revision/activation checks still apply.",
    ],
    [
      "template.driver_config",
      "Caller-supplied driver configuration is not supported by the current integration; it cannot bypass deployment controls.",
    ],
  ],
};

function FieldDetail({ entry }) {
  const section = entry.section;
  const constraints = Object.fromEntries(
    Object.entries(entry).filter(([key]) =>
      [
        "type",
        "enum",
        "itemChoices",
        "pattern",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
      ].includes(key),
    ),
  );
  const hasDefault = Object.hasOwn(entry, "default");
  const example =
    entry.path === "agentSandbox.spec"
      ? sources.examples.agentSandbox
      : entry.path === "openShell.spec"
        ? sources.examples.openShell
        : null;
  return (
    <section
      className="config-reference-detail"
      aria-label="Selected setting"
      aria-live="polite"
    >
      <span className="eyebrow">{section.label}</span>
      <h2>
        <code>{entry.path}</code>
      </h2>
      <p className="config-setting-summary">{entry.summary}</p>
      <div className="config-readers" aria-label="Involved systems">
        {Object.entries(systems).map(([id, title]) => (
          <span
            key={id}
            className={section.readers.includes(id) ? "active" : ""}
            aria-label={`${title}: ${section.readers.includes(id) ? "involved" : "not involved"}`}
          >
            {title}
          </span>
        ))}
      </div>
      <p className="small-note">
        Highlighted systems participate in this setting's path. Native systems
        use resolved native fields; they do not interpret portal-only keys.
      </p>
      <dl className="config-responsibilities">
        <div>
          <dt>Configured by</dt>
          <dd>{section.owner}</dd>
        </div>
        <div>
          <dt>Enforced by</dt>
          <dd>{section.enforcement}</dd>
        </div>
        <div>
          <dt>Portal editing</dt>
          <dd>{section.editing}</dd>
        </div>
        <div>
          <dt>When it changes</dt>
          <dd>{section.changes}</dd>
        </div>
      </dl>
      {nativeFields[entry.path] && (
        <div className="config-native-fields">
          <h3>Native fields and portal boundaries</h3>
          <p>
            The native spec stays native. These are portal-relevant paths and
            restrictions, rather than a replacement schema for every upstream
            field.
          </p>
          <dl>
            {nativeFields[entry.path].map(([path, text]) => (
              <div key={path}>
                <dt>
                  <code>{path}</code>
                </dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
      {entry.path === "envoyEgress" && (
        <p className="config-reference-warning">
          Unavailable: a non-null value is rejected by the current profile
          validator.
        </p>
      )}
      <details className="config-source-details">
        <summary>Source definition, defaults & constraints</summary>
        <p>
          <code>{sourceFiles[entry.scope]}</code>
        </p>
        {entry.scope === "profile" && (
          <p>
            Required applies only when the containing optional object exists.
            Fields without an explicit default can be required, optional or
            resolved by the backend.
          </p>
        )}
        <CodeBlock language="json" title="Source constraints">
          {JSON.stringify(
            {
              ...constraints,
              ...(entry.required !== undefined
                ? { required: entry.required }
                : {}),
            },
            null,
            2,
          )}
        </CodeBlock>
        {hasDefault ? (
          <CodeBlock
            language="json"
            title={
              entry.scope === "deployment"
                ? "Default from chart values.yaml"
                : entry.scope === "environment"
                  ? "Process default from source (before deployment wiring)"
                  : "Explicit model default"
            }
          >
            {JSON.stringify(entry.default, null, 2)}
          </CodeBlock>
        ) : (
          <p>
            {entry.scope === "deployment"
              ? "This field has no default in values.yaml. It is declared by the chart schema; supply it when needed."
              : "No explicit default at this field in the exported source. Parent-object defaults or renderer behavior can still apply."}
          </p>
        )}
      </details>
      {example && (
        <details className="config-source-details">
          <summary>
            Full{" "}
            {entry.path === "agentSandbox.spec" ? "Agent Sandbox" : "OpenShell"}{" "}
            profile example
          </summary>
          <p>
            Source example, not a complete installation. Replace placeholder
            images, configure the matching backend and approve an installed
            runtime. The default image provides basic tools; extra CLIs must be
            included in a custom image.
          </p>
          <CodeBlock language="json">
            {JSON.stringify(example, null, 2)}
          </CodeBlock>
        </details>
      )}
    </section>
  );
}

export default function ConfigurationReference({ scope }) {
  const [query, setQuery] = useState("");
  const initialPath = {
    profile: "agentSandbox.spec",
    deployment: "settings.sandboxSecurityContext.runAsUser",
    state: "record.id",
    environment: "PORTAL_DATABASE_URL",
  }[scope];
  const [selectedPath, setSelectedPath] = useState(initialPath);
  const entries = searchEntries(scope, query);
  const selected =
    entries.find((entry) => entry.path === selectedPath) || entries[0];
  return (
    <>
      <div className="config-reference-grid">
        <aside className="config-reference-nav" aria-label="Settings index">
          <label htmlFor="configuration-search">
            Search {scopes[scope].toLowerCase()}
          </label>
          <input
            id="configuration-search"
            type="search"
            placeholder="e.g. UID, storage, helpers"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <span className="config-result-count" role="status">
            {entries.length} of {sources[scope].length} fields
          </span>
          <div className="config-field-index">
            {groups
              .filter((item) => item.scope === scope)
              .map((section) => {
                const fields = entries.filter(
                  (entry) => entry.section.id === section.id,
                );
                return fields.length ? (
                  <details
                    key={section.id}
                    open={Boolean(query) || selected?.section.id === section.id}
                  >
                    <summary>
                      {section.label}
                      <span>{fields.length}</span>
                    </summary>
                    <div>
                      {fields.map((entry) => (
                        <button
                          key={entry.path}
                          aria-pressed={selected?.path === entry.path}
                          onClick={() => setSelectedPath(entry.path)}
                        >
                          <code>
                            {entry.path.split(/([._])/).map((part, index) => (
                              <React.Fragment key={index}>
                                {part}
                                {part === "." || part === "_" ? <wbr /> : null}
                              </React.Fragment>
                            ))}
                          </code>
                        </button>
                      ))}
                    </div>
                  </details>
                ) : null;
              })}
          </div>
        </aside>
        {selected ? (
          <FieldDetail entry={selected} />
        ) : (
          <section className="config-reference-detail">
            <h2>No matching settings</h2>
            <p>
              Try another search term. Other configuration subjects have their
              own pages in the sidebar.
            </p>
            <button
              className="button button--secondary"
              onClick={() => setQuery("")}
            >
              Clear search
            </button>
          </section>
        )}
      </div>
      <p className="example-note">
        Reference for source chart {sources.chartVersion}, exported from
        checked-in definitions. This page does not read a live deployment.
        Coverage checks flag outdated or missing fields. Native
        Kubernetes/OpenShell specs and arbitrary extraObjects remain owned by
        their native APIs. <Link to="/guide/profiles">About profiles →</Link>
      </p>
    </>
  );
}
