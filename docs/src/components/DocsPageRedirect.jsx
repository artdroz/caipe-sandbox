import React from "react";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import { Redirect, useLocation } from "@docusaurus/router";

export default function DocsPageRedirect({ to, title }) {
  const { search, hash } = useLocation();
  const destination = useBaseUrl(to) + search + hash;
  return (
    <Layout title={title}>
      <Redirect to={destination} />
      <main className="explorer-page shell-width">
        <p>
          Continue to <Link to={destination}>{title}</Link> in the
          documentation.
        </p>
      </main>
    </Layout>
  );
}
