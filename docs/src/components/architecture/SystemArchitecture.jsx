import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "@docusaurus/Link";
import Icon from "./PlaygroundIcon";
import { connectorPath } from "./connector-path.mjs";
import styles from "./playground.module.css";
import {
  integrations,
  workloadText,
  requiredIntegrations,
  interactions,
  groupInteractions,
  initialSelection,
  available,
  normalizePlayground,
  readPlayground,
  playgroundSearch,
  makePlayground,
  describeInteraction,
} from "./playground-model.mjs";

function usePresence(items) {
  const [shown, setShown] = useState(() =>
    items.map((item) => ({ ...item, phase: "present" })),
  );
  useEffect(() => {
    const ids = new Set(items.map((item) => item.id));
    setShown((previous) => {
      const old = new Set(
        previous.filter((item) => item.phase !== "exit").map((item) => item.id),
      );
      return [
        ...items.map((item) => ({
          ...item,
          phase: old.has(item.id) ? "present" : "enter",
        })),
        ...previous
          .filter((item) => !ids.has(item.id))
          .map((item) => ({ ...item, phase: "exit" })),
      ];
    });
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() =>
        setShown((previous) =>
          previous.map((item) =>
            item.phase === "enter" ? { ...item, phase: "present" } : item,
          ),
        ),
      );
    });
    const timer = setTimeout(
      () =>
        setShown((previous) =>
          previous.filter((item) => item.phase !== "exit"),
        ),
      300,
    );
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
    };
  }, [items]);
  return shown;
}

function Diagram({ model, selected, onSelect, motion, cycle, prefix }) {
  const active = new Set(model.activeEdges);
  const visible = useMemo(
    () => model.edges.filter((edge) => edge.general || active.has(edge.id)),
    [model],
  );
  const nodes = usePresence(model.nodes),
    edges = usePresence(visible),
    overview = model.state.interaction === "overview";
  const activeNodes = new Set(
    model.edges
      .filter((edge) => active.has(edge.id))
      .flatMap((edge) => [edge.from, edge.to]),
  );
  return (
    <div className={`${styles.diagramPanel} ${!motion ? styles.paused : ""}`}>
      <div
        className={styles.diagramScroll}
        tabIndex={0}
        role="region"
        aria-label="System architecture playground; scroll horizontally on narrow screens"
      >
        <div
          className={styles.diagram}
          style={{ aspectRatio: `${model.width} / ${model.height}` }}
        >
          <svg
            className={styles.wires}
            viewBox={`0 0 ${model.width} ${model.height}`}
            aria-hidden="true"
          >
            <defs>
              {[
                "core",
                "omnigent",
                "openshell",
                "storage",
                "identity",
                "network",
              ].map((tone) => (
                <marker
                  key={tone}
                  id={`${prefix}-${tone}`}
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto"
                >
                  <path
                    d="M0 1 L9 5 L0 9z"
                    className={styles[`fill_${tone}`]}
                  />
                </marker>
              ))}
            </defs>
            {model.groups.map((group) => (
              <g key={group.id}>
                <rect
                  x={group.x}
                  y={group.y}
                  width={group.w}
                  height={group.h}
                  rx="15"
                  className={`${styles.group} ${styles[`${group.id}Group`]}`}
                />
                <text
                  x={group.x + (group.labelOffset ?? 16)}
                  y={group.y + 21}
                  className={styles.groupLabel}
                >
                  {group.title}
                </text>
              </g>
            ))}
            {edges.map((edge) => {
              const live = active.has(edge.id) && edge.phase !== "exit";
              const dim = !overview && !live;
              return (
                <g
                  key={edge.id}
                  className={`${styles.connection} ${styles[`tone_${edge.tone}`]} ${dim ? styles.dimWire : ""} ${edge.phase === "enter" ? styles.enteringWire : ""} ${edge.phase === "exit" ? styles.exitingWire : ""}`}
                  data-connection={edge.id}
                  data-active={live}
                >
                  <path
                    className={`${styles.wire} ${live ? styles.activeWire : ""}`}
                    d={connectorPath(edge.points)}
                    markerEnd={`url(#${prefix}-${edge.tone})`}
                  />
                  {live && (
                    <path
                      key={cycle}
                      className={styles.signal}
                      d={connectorPath(edge.points)}
                    />
                  )}
                  {edge.labelAt && (
                    <g
                      transform={`translate(${edge.labelAt.join(",")}) rotate(${edge.labelAngle ?? 0})`}
                    >
                      <rect
                        x={-edge.label.length * 3.2 - 9}
                        y="-12"
                        width={edge.label.length * 6.4 + 18}
                        height="24"
                        rx="6"
                        className={styles.labelBack}
                      />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        className={styles.wireLabel}
                      >
                        {edge.label}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </svg>
          {model.groups
            .filter((group) => group.kata)
            .map((group) => (
              <span
                key={`${group.id}-kata`}
                className={styles.kataBadge}
                role="img"
                aria-label="Kata runtime: micro VM isolation"
                title="Kata runtime: micro VM isolation"
                style={{
                  right: `${((model.width - group.x - group.w + 14) / model.width) * 100}%`,
                  top: `${((group.y + 8) / model.height) * 100}%`,
                }}
              >
                <Icon name="kata" />
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  aria-hidden="true"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z"
                  />
                </svg>
              </span>
            ))}
          {nodes.map((node) => (
            <button
              type="button"
              key={node.id}
              data-playground-node={node.id}
              disabled={node.phase === "exit"}
              aria-hidden={node.phase === "exit" ? true : undefined}
              aria-pressed={node.id === selected}
              onClick={() => onSelect(node.id)}
              className={`${styles.component} ${styles[`tone_${node.tone}`]} ${node.id === selected ? styles.selected : ""} ${!overview && !activeNodes.has(node.id) ? styles.dimComponent : ""} ${node.phase === "enter" ? styles.entering : ""} ${node.phase === "exit" ? styles.exiting : ""} ${node.ports ? styles.withPorts : ""}`}
              style={{
                left: `${(node.x / model.width) * 100}%`,
                top: `${(node.y / model.height) * 100}%`,
                width: `${(node.w / model.width) * 100}%`,
                height: `${(node.h / model.height) * 100}%`,
              }}
            >
              <span className={styles.componentHeader}>
                <span className={styles.componentIcon}>
                  <Icon name={node.icon} />
                </span>
                <span>
                  <strong>{node.title}</strong>
                  <small>{node.subtitle}</small>
                </span>
              </span>
              {node.ports && (
                <span className={styles.ports}>
                  {node.ports.map((port) => (
                    <span key={port}>
                      <i />
                      {port}
                    </span>
                  ))}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.legend}>
        <span className={styles.tone_core}>
          <i />
          Portal / Kubernetes
        </span>
        {model.state.integrations.map((id) => (
          <span
            key={id}
            className={
              styles[`tone_${integrations.find((i) => i.id === id).tone}`]
            }
          >
            <i />
            {integrations.find((i) => i.id === id).label}
          </span>
        ))}
        <span className={styles.tone_network}>
          <i />
          Network egress
        </span>
        <span className={styles.tone_storage}>
          <i />
          Persistence
        </span>
        <span className={styles.legendNote}>
          Motion shows connections and selected paths, not live traffic.
        </span>
      </div>
    </div>
  );
}

export default function SystemArchitecture() {
  const [state, setState] = useState({
    integrations: initialSelection,
    interaction: "overview",
  });
  const [ready, setReady] = useState(false),
    [selected, setSelected] = useState("portal"),
    [motion, setMotion] = useState(true),
    [cycle, setCycle] = useState(0),
    [expanded, setExpanded] = useState(false),
    [announcement, setAnnouncement] = useState("");
  const detailRef = useRef(null),
    wideRef = useRef(null),
    prefix = "pg" + useId().replaceAll(":", "");
  useEffect(() => {
    setState(readPlayground(window.location.search));
    setReady(true);
    const pop = () => setState(readPlayground(window.location.search));
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  useEffect(() => {
    if (ready)
      window.history.replaceState(
        window.history.state,
        "",
        window.location.pathname +
          playgroundSearch(state) +
          window.location.hash,
      );
  }, [state, ready]);
  useEffect(() => {
    if (!expanded) return;
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e) => {
      if (e.key === "Escape") {
        setExpanded(false);
        wideRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = old;
      window.removeEventListener("keydown", onKey);
    };
  }, [expanded]);
  const model = useMemo(() => makePlayground(state), [state]);
  const selectedNode =
    model.nodes.find((n) => n.id === selected) ||
    model.nodes.find((n) => n.id === "portal");
  const description = describeInteraction(state),
    currentAction = interactions.find((i) => i.id === state.interaction);
  function toggle(id) {
    setState((previous) => {
      const ids = previous.integrations.includes(id)
        ? previous.integrations.filter((i) => i !== id)
        : [...previous.integrations, id];
      const next = normalizePlayground({
        integrations: ids,
        interaction: previous.interaction,
      });
      if (next.interaction !== previous.interaction)
        setAnnouncement(
          "The selected interaction requires an integration that was removed. Showing the general architecture.",
        );
      else setAnnouncement("");
      return next;
    });
  }
  const has = (id) => state.integrations.includes(id);
  const selectedConnections = model.edges.filter(
    (edge) =>
      (edge.general || model.activeEdges.includes(edge.id)) &&
      (edge.from === selectedNode.id || edge.to === selectedNode.id),
  );
  return (
    <section
      className={`${styles.playground} ${expanded ? styles.expanded : ""}`}
      aria-label="System architecture integration playground"
    >
      <header className={styles.intro}>
        <p>Integrations</p>
        <button
          type="button"
          ref={wideRef}
          className={styles.quietButton}
          onClick={() => setExpanded((v) => !v)}
          aria-pressed={expanded}
        >
          {expanded ? "Exit wide view · Esc" : "Wide view"}
        </button>
      </header>
      <fieldset className={styles.integrationPicker}>
        <legend className={styles.screenReaderOnly}>Integrations</legend>
        <div className={styles.integrationGrid}>
          {[...requiredIntegrations, ...integrations].map((item) => (
            <label
              key={item.id}
              className={`${styles.integrationTile} ${styles[`tone_${item.tone}`]} ${item.required || has(item.id) ? styles.enabledTile : ""} ${item.required ? styles.requiredTile : ""}`}
              title={
                item.required
                  ? `${item.label} is required and cannot be disabled.`
                  : undefined
              }
            >
              <input
                type="checkbox"
                aria-label={
                  item.required
                    ? `${item.label} (required)`
                    : `Enable ${item.label}`
                }
                checked={item.required || has(item.id)}
                disabled={item.required}
                onChange={() => toggle(item.id)}
              />
              <span className={styles.integrationIcon}>
                <Icon name={item.icon} />
              </span>
              <span className={styles.integrationText}>
                <strong>{item.label}</strong>
                <small>{item.role}</small>
              </span>
              <span aria-hidden="true" className={styles.checkmark}>
                {item.required || has(item.id) ? "✓" : "+"}
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div className={styles.actionBar}>
        <div className={styles.actionChoice}>
          <label htmlFor={`${prefix}-interaction`}>
            User / operator interaction
          </label>
          <select
            id={`${prefix}-interaction`}
            value={state.interaction}
            onChange={(event) => {
              setState((previous) =>
                normalizePlayground({
                  ...previous,
                  interaction: event.target.value,
                }),
              );
              setCycle((v) => v + 1);
              setAnnouncement("");
            }}
          >
            <option value="overview">Architecture — no interaction</option>
            {groupInteractions(state).map((group) => (
              <optgroup key={group.id} label={group.label}>
                {group.items.map((item) => (
                  <option
                    key={item.id}
                    value={item.id}
                    disabled={!available(item, state.integrations)}
                  >
                    {workloadText(item.label, state.integrations)}
                    {!available(item, state.integrations)
                      ? ` — enable ${item.requires.map((id) => integrations.find((i) => i.id === id).label).join(" + ")}`
                      : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <button
          type="button"
          className={styles.quietButton}
          aria-pressed={!motion}
          onClick={() => setMotion((v) => !v)}
        >
          {motion ? "Ⅱ Pause motion" : "▶ Resume motion"}
        </button>
        {state.interaction !== "overview" && (
          <button
            type="button"
            className={styles.quietButton}
            onClick={() => setCycle((v) => v + 1)}
          >
            ↻ Replay path
          </button>
        )}
      </div>
      {state.interaction !== "overview" && (
        <p className={styles.actionSummary}>{description.summary}</p>
      )}
      <p className={styles.screenReaderOnly} role="status">
        {announcement}
      </p>
      <Diagram
        model={model}
        selected={selectedNode.id}
        onSelect={setSelected}
        motion={motion}
        cycle={cycle}
        prefix={prefix}
      />
      <div className={styles.prerequisites}>
        <details>
          <summary>Selection rules</summary>
          <ul>
            <li>
              Agent Sandbox is required and manages provisioning. Kata is
              optional and selected by default. With Kata enabled, the Pod runs
              inside a micro VM; otherwise this view shows a standard Pod.
            </li>
            <li>
              Omnigent adds its browser UI, server and workload host connection.
              Its native tool login remains separate from portal sign-in.
            </li>
            <li>
              OpenShell keeps Agent Sandbox compute and adds gateway/supervisor
              services. It replaces the portal’s direct exec path and requires
              native policy, admission, network and runtime prerequisites for
              the deployed configuration.
            </li>
            <li>
              Native tool login, portal sign-in and Omnigent UI sign-in are
              separate. Only interactions supported by the selection can be
              chosen.
            </li>
          </ul>
        </details>
      </div>
      <div className={styles.canvasFooter}>
        <span>
          Selected: <strong>{selectedNode.title}</strong>
        </span>
        <button
          type="button"
          onClick={() =>
            detailRef.current?.scrollIntoView({
              behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
                .matches
                ? "auto"
                : "smooth",
              block: "start",
            })
          }
        >
          Component details ↓
        </button>
      </div>
      {description.steps.length > 0 && (
        <section className={styles.walkthrough} aria-live="polite">
          <h2>{workloadText(currentAction.label, state.integrations)}</h2>
          <ol>
            {description.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          {description.note && (
            <p className={styles.pathNote}>{description.note}</p>
          )}
        </section>
      )}
      <section
        className={`${styles.componentDetails} ${styles[`tone_${selectedNode.tone}`]}`}
        ref={detailRef}
        aria-live="polite"
        aria-label="Selected component details"
      >
        <header>
          <span className={styles.detailIcon}>
            <Icon name={selectedNode.icon} />
          </span>
          <div>
            <p>Selected component</p>
            <h2>{selectedNode.title}</h2>
          </div>
          <Link to={selectedNode.docs}>Read more →</Link>
        </header>
        <p className={styles.detailBody}>{selectedNode.body}</p>
        <dl className={styles.detailGrid}>
          <div>
            <dt>Runs where</dt>
            <dd>{selectedNode.where}</dd>
          </div>
          <div>
            <dt>Identity and access</dt>
            <dd>{selectedNode.identity}</dd>
          </div>
          <div>
            <dt>State ownership</dt>
            <dd>{selectedNode.state}</dd>
          </div>
        </dl>
        <div className={styles.connections}>
          <h3>Connections</h3>
          {selectedConnections.map((edge) => (
            <p key={edge.id}>
              <strong>
                {model.nodes.find((n) => n.id === edge.from)?.title}
              </strong>
              <span>→</span>
              <strong>
                {model.nodes.find((n) => n.id === edge.to)?.title}
              </strong>
              <small>{edge.label}</small>
            </p>
          ))}
        </div>
      </section>
      <p className={styles.reference}>
        Reference implementation, not live deployment status. Images, native
        login and policy prerequisites must be configured in the selected
        profile. The OSS repository currently contains the documentation
        preview.
      </p>
    </section>
  );
}
