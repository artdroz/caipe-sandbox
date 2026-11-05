import React from "react";
import Layout from "@theme/Layout";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import { Redirect, useLocation } from "@docusaurus/router";
import { readPlayground, playgroundSearch } from "./playground-model.mjs";

export default function ArchitectureRedirect() {
  const { search, hash } = useLocation();
  const destination =
    useBaseUrl("/guide/architecture") +
    playgroundSearch(readPlayground(search)) +
    hash;
  return (
    <Layout title="System architecture">
      <Redirect to={destination} />
      <main className="explorer-page shell-width">
        <p>
          The architecture views are now combined in{" "}
          <Link to={destination}>System architecture</Link>.
        </p>
      </main>
    </Layout>
  );
}
