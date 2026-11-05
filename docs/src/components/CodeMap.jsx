import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import Link from "@docusaurus/Link";
import Icon from "./architecture/PlaygroundIcon";
import { connectorPath } from "./architecture/connector-path.mjs";
import styles from "./codemap/code-map.module.css";
import {
  zones,
  modules,
  makeCodeMap,
  normalizeCodeMap,
  readCodeMap,
  codeMapSearch,
} from "./codemap/model.mjs";

export default function CodeMap() {
  const [state, setState] = useState(() => normalizeCodeMap());
  const [ready, setReady] = useState(false);
  const detailRef = useRef(null);
  const prefix = "code" + useId().replaceAll(":", "");
  useEffect(() => {
    const read = () => setState(readCodeMap(window.location.search));
    read();
    setReady(true);
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);
  useEffect(() => {
    if (ready)
      window.history.replaceState(
        window.history.state,
        "",
        window.location.pathname + codeMapSearch(state) + window.location.hash,
      );
  }, [state, ready]);
  const model = useMemo(() => makeCodeMap(state), [state]);
  const selected = model.components.find((item) => item.id === state.component);
  const related = model.connections.filter(
    (edge) => edge.from === selected.id || edge.to === selected.id,
  );
  const select = (id) => setState(normalizeCodeMap({ component: id }));
  const showDetails = () =>
    detailRef.current?.scrollIntoView({
      block: "start",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  return (
    <div className={styles.codeMap}>
      <header className={styles.heading}>
        <div>
          <h1>Code map</h1>
          <p>
            Explore the components, their responsibilities and how they connect.
            Select a box for its source files and details.
          </p>
        </div>
        <Link to="/guide/architecture">System architecture ↗</Link>
      </header>
      <p className={styles.mapNote}>
        Boxes inside <strong>Portal API</strong> are modules in one Python
        process per replica. Terminal I/O uses a bounded thread pool; sessions
        and maintenance also use async tasks. Sandbox Provider represents the
        selected external backend. Database is persisted state: a SQLite file or
        PostgreSQL service.{" "}
        <Link to="/guide/metadata">Database and persistence →</Link>
      </p>
      <div className={styles.mapPanel}>
        <div
          className={styles.mapScroll}
          role="region"
          tabIndex={0}
          aria-label="Component code map; scroll horizontally on narrow screens"
        >
          <div
            className={styles.diagram}
            style={{ aspectRatio: `${model.width} / ${model.height}` }}
          >
            <svg
              viewBox={`0 0 ${model.width} ${model.height}`}
              className={styles.wires}
              aria-hidden="true"
            >
              <defs>
                {Object.keys(zones).map((zone) => (
                  <marker
                    key={zone}
                    id={`${prefix}-${zone}`}
                    viewBox="0 0 10 10"
                    refX="8"
                    refY="5"
                    markerWidth="5"
                    markerHeight="5"
                    orient="auto-start-reverse"
                  >
                    <path
                      d="M0 1 L9 5 L0 9z"
                      className={styles[zone]}
                      fill="var(--tone)"
                    />
                  </marker>
                ))}
              </defs>
              {model.groups.map((group) => (
                <g key={group.id} className={styles[group.id]}>
                  <rect
                    x={group.x}
                    y={group.y}
                    width={group.w}
                    height={group.h}
                    rx="15"
                    className={styles.boundary}
                  />
                  <text
                    x={group.x + 16}
                    y={group.y + 22}
                    className={styles.groupTitle}
                  >
                    {group.title}
                  </text>
                  <text
                    x={group.x + 16}
                    y={group.y + 40}
                    className={styles.groupSubtitle}
                  >
                    {group.subtitle}
                  </text>
                </g>
              ))}
              {model.lanes.map((lane) => (
                <text
                  key={lane.title}
                  x={lane.x}
                  y={lane.y}
                  className={styles.laneLabel}
                >
                  {lane.title}
                </text>
              ))}
              {model.connections.map((edge) => {
                const active = related.some((item) => item.id === edge.id);
                const source = model.components.find(
                  (item) => item.id === edge.from,
                );
                return (
                  <g
                    key={edge.id}
                    className={`${styles.connection} ${styles[source.zone]} ${active ? styles.activeConnection : ""}`}
                    data-code-connection={edge.id}
                    data-bidirectional={edge.bidirectional || undefined}
                  >
                    <path
                      d={connectorPath(edge.points, 10)}
                      className={styles.wire}
                      markerStart={
                        edge.bidirectional
                          ? `url(#${prefix}-${source.zone})`
                          : undefined
                      }
                      markerEnd={`url(#${prefix}-${source.zone})`}
                    />
                    {active && (
                      <path
                        d={connectorPath(edge.points, 10)}
                        className={styles.signal}
                      />
                    )}
                    <g
                      transform={`translate(${edge.labelAt.join(",")}) rotate(${edge.angle})`}
                    >
                      <rect
                        x={-edge.label.length * 2.8 - 7}
                        y="-10"
                        width={edge.label.length * 5.6 + 14}
                        height="20"
                        rx="5"
                        className={styles.labelBack}
                      />
                      <text
                        textAnchor="middle"
                        dominantBaseline="central"
                        className={styles.edgeLabel}
                      >
                        {edge.label}
                      </text>
                    </g>
                  </g>
                );
              })}
            </svg>
            {model.components.map((item) => (
              <button
                key={item.id}
                type="button"
                data-code-component={item.id}
                aria-pressed={item.id === selected.id}
                aria-controls="code-component-details"
                onClick={() => select(item.id)}
                className={`${styles.component} ${styles[item.zone]} ${item.id === selected.id ? styles.selected : ""}`}
                style={{
                  left: `${(item.x / model.width) * 100}%`,
                  top: `${(item.y / model.height) * 100}%`,
                  width: `${(item.w / model.width) * 100}%`,
                  height: `${(item.h / model.height) * 100}%`,
                }}
              >
                <span className={styles.componentIcon}>
                  <Icon name={item.icon} />
                </span>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.subtitle}</small>
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className={styles.mapFooter}>
          <span>
            Selected: <strong>{selected.title}</strong>
          </span>
          <button type="button" onClick={showDetails}>
            Component details ↓
          </button>
        </div>
      </div>
      <p className={styles.hint}>
        Arrows show the main calls, native transports and startup relationships.
        Highlighted connections touch the selected component; motion is
        illustrative.
      </p>
      <section
        ref={detailRef}
        id="code-component-details"
        className={`${styles.detail} ${styles[selected.zone]}`}
        aria-label="Selected code component"
        aria-live="polite"
      >
        <header>
          <span className={styles.detailIcon}>
            <Icon name={selected.icon} />
          </span>
          <div>
            <span className={styles.zoneBadge}>
              {zones[selected.zone].label}
            </span>
            <h2>{selected.title}</h2>
          </div>
        </header>
        <p className={styles.summary}>{selected.summary}</p>
        <div className={styles.detailGrid}>
          <div>
            <h3>What it handles</h3>
            <ul className={styles.handles}>
              {selected.handles.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            {selected.terminalWorker && (
              <>
                <h3>Terminal session tasks</h3>
                <p className={styles.boundaryNote}>
                  {selected.terminalWorker.summary}
                </p>
                <ul className={styles.handles}>
                  {selected.terminalWorker.handles.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
                <p className={styles.boundaryNote}>
                  {selected.terminalWorker.boundary}
                </p>
                <code className={styles.symbol}>
                  {selected.terminalWorker.symbols}
                </code>
              </>
            )}
            <h3>Execution boundary</h3>
            <p className={styles.boundaryNote}>{selected.boundary}</p>
            {selected.symbols && (
              <code className={styles.symbol}>{selected.symbols}</code>
            )}
            <h3>Connected components</h3>
            <div className={styles.relationships}>
              {related.map((edge) => {
                const from = model.components.find(
                  (item) => item.id === edge.from,
                );
                const to = model.components.find((item) => item.id === edge.to);
                const other = from.id === selected.id ? to : from;
                return (
                  <button
                    key={edge.id}
                    type="button"
                    onClick={() => select(other.id)}
                  >
                    <span>
                      {from.title} {edge.bidirectional ? "↔" : "→"} {to.title}
                    </span>
                    <small>{edge.label}</small>
                  </button>
                );
              })}
            </div>
          </div>
          <div>
            <h3>
              {selected.sourceHeading ||
                (selected.files.length
                  ? "Source files"
                  : "External implementation")}
            </h3>
            {selected.files.length ? (
              <dl className={styles.files}>
                {selected.files.map((id) => (
                  <div key={id}>
                    <dt>
                      <code>{modules[id].path}</code>
                    </dt>
                    <dd>{modules[id].job}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className={styles.boundaryNote}>{selected.external}</p>
            )}
          </div>
        </div>
      </section>
      <p className={styles.reference}>
        Paths are relative to this repository root. Boxes represent
        responsibilities and process boundaries, not one deployment per source
        file. The portal, workload tools and charts are included in this
        repository.
      </p>
    </div>
  );
}
