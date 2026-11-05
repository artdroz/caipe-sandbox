import React from "react";
import useBaseUrl from "@docusaurus/useBaseUrl";
import { icon } from "./portal-icons/icons";

const portalNames = {
  browser: "external",
  portal: "server",
  kubernetes: "network",
  controller: "refresh",
  config: "settings",
  host: "server",
  openshell: "shield",
};

export default function PlaygroundIcon({ name, className }) {
  const kataLogo = useBaseUrl("/img/kata-logo.svg");
  if (name === "kata")
    return (
      <img src={kataLogo} className={className} alt="" aria-hidden="true" />
    );
  return (
    <span
      className={className}
      style={{ display: "contents" }}
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: icon(portalNames[name] || name) }}
    />
  );
}
