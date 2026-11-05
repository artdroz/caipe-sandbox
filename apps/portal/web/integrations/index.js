import openshell from "./openshell/index.js";
import kubernetes from "./kubernetes/index.js";
import { integrationRegistry } from "./registry.js";
import "./policy.css";
import "./security.css";

const registry = integrationRegistry([openshell,kubernetes]);

export function openIntegrationPanel(id, ...args) {
  return registry.openPanel(id,...args);
}

export const mountIntegrationCreation = (...args) => registry.mountCreation(...args);
export const openSecurityPanel = (...args) => registry.openSecurity(...args);
