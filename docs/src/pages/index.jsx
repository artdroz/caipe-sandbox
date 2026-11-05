import React from "react";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";

const sections = [
  {
    title: "Getting started",
    to: "/guide/getting-started",
    description:
      "Deploy the portal with Helm, configure sign-in, and verify your first sandbox.",
  },
  {
    title: "Profiles",
    to: "/guide/profiles",
    description:
      "Configure images, startup commands, helpers, and resource limits.",
  },
  {
    title: "Helm chart values",
    to: "/guide/helm-values",
    description:
      "Review chart inputs, repository defaults and deployment overrides.",
  },
  {
    title: "Code map",
    to: "/guide/code-map",
    description:
      "Find the modules responsible for API routes, lifecycle, execution, and storage.",
  },
  {
    title: "Deployment",
    to: "/guide/deployment",
    description:
      "Review platform prerequisites, authentication, and deployment checks.",
  },
  {
    title: "Capacity and scaling",
    to: "/guide/scaling",
    description:
      "Plan replica counts, workload limits, terminal recovery and capacity tests.",
  },
];

export default function Home() {
  const logo = useBaseUrl("/img/caipe-sandbox-logo.svg");
  return (
    <Layout
      title="Platform operator documentation"
      description="CAIPE Sandbox platform operator documentation: deployment, profiles, isolation, configuration, architecture, and lifecycle."
    >
      <main className="developer-home shell-width">
        <header className="docs-intro">
          <div>
            <p className="docs-label">Platform operator documentation</p>
            <h1>CAIPE Sandbox</h1>
            <p className="docs-subtitle">Developer micro VMs on Kubernetes.</p>
            <p className="docs-description">
              A portal for creating and managing persistent environments for
              tools and AI agents. Configure micro VMs through profiles, access
              them through terminals, and retain files across suspend and
              resume.
            </p>
            <div className="docs-actions">
              <Link className="button button--primary" to="/guide/overview">
                Read the docs
              </Link>
              <Link
                className="button button--outline button--secondary"
                to="/guide/architecture"
              >
                Architecture
              </Link>
            </div>
          </div>
          <div className="project-mark">
            <img
              src={logo}
              alt="CAIPE character inside a cyan sandbox cube"
              width="300"
              height="300"
            />
          </div>
        </header>

        <section
          className="architecture-summary"
          aria-label="Architecture summary"
        >
          <div>
            <strong>Portal</strong>
            <span>Identity, profiles, access, and inventory</span>
          </div>
          <span className="architecture-arrow" aria-hidden="true">
            →
          </span>
          <div>
            <strong>Runtime integrations</strong>
            <span>Agent Sandbox · OpenShell</span>
          </div>
          <span className="architecture-arrow" aria-hidden="true">
            →
          </span>
          <div>
            <strong>Micro VMs</strong>
            <span>Execution, persistent storage, and tool login</span>
          </div>
        </section>

        <section
          className="documentation-index"
          aria-labelledby="documentation-title"
        >
          <div className="documentation-heading">
            <h2 id="documentation-title">Documentation</h2>
            <Link to="/guide/overview">All guides →</Link>
          </div>
          <div className="documentation-grid">
            {sections.map(({ title, to, description }) => (
              <Link className="documentation-entry" to={to} key={to}>
                <div>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </div>
                <span aria-hidden="true">→</span>
              </Link>
            ))}
          </div>
        </section>
        <nav className="reference-links" aria-label="Additional documentation">
          <span>Reference</span>
          <Link to="/guide/security">Security</Link>
          <Link to="/guide/metadata">Database and persistence</Link>
        </nav>
      </main>
    </Layout>
  );
}
