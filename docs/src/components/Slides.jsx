import React, { useEffect, useState } from "react";
import Link from "@docusaurus/Link";

const slides = [
  {
    kicker: "01 / THE IDEA",
    title: "CAIPE Sandbox overview",
    text: "A persistent environment for tools, code and native login state, with a shared portal for access and lifecycle.",
    points: [
      ["Choose", "Start from an administrator-managed profile."],
      ["Work", "Open terminals and run your tools inside the micro VM."],
      ["Return", "Suspend compute and resume against retained files."],
    ],
    link: "/guide/overview",
    label: "What is CAIPE Sandbox?",
  },
  {
    kicker: "02 / THE DEVELOPER JOURNEY",
    title: "Micro VM lifecycle",
    text: "Portal authentication and tool authentication are separate. The profile defines the environment; the developer chooses permitted resources.",
    points: [
      [
        "Portal identity",
        "Verified sign-in establishes who can access the micro VM.",
      ],
      [
        "Micro VM profile",
        "Image, startup, helpers and persistent mounts form the preset.",
      ],
      ["Native tools", "The tool owns its login flow inside the micro VM."],
    ],
    link: "/guide/getting-started",
    label: "Walk through your first micro VM",
  },
  {
    kicker: "03 / CONFIGURATION",
    title: "Configuration ownership",
    text: "Profile defaults, developer choices and platform controls resolve into native runtime fields.",
    points: [
      [
        "Administrator",
        "Images, helpers, startup and editable defaults/ranges.",
      ],
      ["Developer", "Offered profile, display name and sizes within bounds."],
      [
        "Platform",
        "Runtime, capacity, storage, admission and network enforcement.",
      ],
    ],
    link: "/guide/configuration",
    label: "Explore the configuration",
  },
  {
    kicker: "04 / ARCHITECTURE",
    title: "Runtime integration boundary",
    text: "The portal keeps access decisions common while each integration owns provisioning, lifecycle and terminal transport.",
    points: [
      [
        "Common control plane",
        "Profiles, authorization, sharing, quotas and inventory model.",
      ],
      ["Native integration", "Agent Sandbox or optional OpenShell behavior."],
      [
        "Explicit boundary",
        "An execution target connects helpers and terminals to the native transport.",
      ],
    ],
    link: "/guide/code-map",
    label: "Follow the code map",
  },
  {
    kicker: "05 / PERSISTENCE",
    title: "State and persistence",
    text: "Persistence spans distinct systems. Suspending a micro VM does not checkpoint its process memory.",
    points: [
      [
        "Micro VM storage",
        "Files, checkpoints and tool login caches under the durable mount.",
      ],
      [
        "Native runtime state",
        "Readiness, native resource identity and policy activation.",
      ],
      [
        "Portal database",
        "Desired manifests, ownership, sharing, operation leases and administrative controls.",
      ],
    ],
    link: "/guide/metadata",
    label: "Understand the persistence boundary",
  },
  {
    kicker: "06 / CURRENT BOUNDARY",
    title: "Deployment and current limitations",
    text: "The portal, workload tools, optional charts and interactive docs live in this repository. Operators choose the runtime and supply platform services.",
    points: [
      [
        "Deployment checks",
        "Prove sign-in, isolation, terminal behavior and storage retention.",
      ],
      [
        "Current constraints",
        "SQLite is single-instance; PostgreSQL supports replicas. Schema changes use Recreate. No general idle detector or warm pool.",
      ],
      [
        "Operator checks",
        "Prove restore, capacity, network boundaries and native provider recovery in your environment.",
      ],
    ],
    link: "/guide/deployment",
    label: "Review deployment ownership",
  },
];

export default function Slides() {
  const [index, setIndex] = useState(0);
  const move = (delta) =>
    setIndex((i) => Math.max(0, Math.min(slides.length - 1, i + delta)));
  useEffect(() => {
    const onKey = (e) => {
      if (
        e.target instanceof HTMLElement &&
        (e.target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName))
      )
        return;
      if (e.key === "ArrowRight") {
        e.preventDefault();
        setIndex((i) => Math.min(slides.length - 1, i + 1));
      }
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setIndex((i) => Math.max(0, i - 1));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const slide = slides[index];
  return (
    <>
      <div className="slides-heading">
        <div>
          <p className="eyebrow">CAIPE SANDBOX / PRESENTATION</p>
          <h1>Sandbox portal overview</h1>
        </div>
        <span className="small-note">Use ← → or the controls below</span>
      </div>
      <section
        className="slide-stage"
        aria-roledescription="carousel"
        aria-label="Sandbox portal overview"
      >
        <div key={index} aria-live="polite" aria-atomic="true">
          <p className="eyebrow">{slide.kicker}</p>
          <h2>{slide.title}</h2>
          <p className="slide-lead">{slide.text}</p>
          <div className="slide-points">
            {slide.points.map(([title, body], i) => (
              <article key={title}>
                <span>0{i + 1}</span>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
          <Link to={slide.link}>{slide.label} →</Link>
        </div>
      </section>
      <nav className="slide-controls" aria-label="Slide controls">
        <button
          className="button button--secondary"
          disabled={index === 0}
          onClick={() => move(-1)}
        >
          ← Previous
        </button>
        <div className="slide-dots">
          {slides.map((s, i) => (
            <button
              key={s.kicker}
              aria-label={`Slide ${i + 1}: ${s.title}`}
              aria-current={i === index ? "step" : undefined}
              onClick={() => setIndex(i)}
            >
              {String(i + 1).padStart(2, "0")}
            </button>
          ))}
        </div>
        <span className="slide-counter">
          {index + 1} / {slides.length}
        </span>
        <button
          className="button button--primary"
          disabled={index === slides.length - 1}
          onClick={() => move(1)}
        >
          Next →
        </button>
      </nav>
    </>
  );
}
