import {icon} from "./icons.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const restricted = policy => policy?.creation_disabled || policy?.sandboxes_disabled;
const namespacePolicy = policy => policy?.creation_disabled || policy?.network_policy != null;

function restrictionDetails(policy, scope) {
  const details = [];
  if (policy.sandboxes_disabled) details.push(`${scope} sandbox access and startup are blocked.`);
  else if (policy.creation_disabled) details.push(`${scope} sandbox creation is disabled; existing sandboxes can keep running.`);
  if (policy.reason) details.push(policy.reason);
  return details.join(" ");
}

function badge(label, detail) {
  return `<span class="admin-policy-badge" tabindex="0" title="${esc(detail)}" aria-label="${esc(label + ": " + detail)}">${icon("shield")}${esc(label)}</span>`;
}

export function globalPolicyBadges(controls = {}) {
  const badges = [];
  if (restricted(controls)) badges.push(badge("Global restrictions", restrictionDetails(controls, "All users’")));
  const users = Object.values(controls.users || {}).filter(restricted).length;
  if (users) badges.push(badge(`User restrictions · ${users}`, `Restrictions are configured for ${users} user account(s). Open Controls & messages to review them.`));
  const namespaces = Object.values(controls.namespaces || {}).filter(namespacePolicy).length;
  if (namespaces) badges.push(badge(`Namespace restrictions · ${namespaces}`, `Creation locks or administrator-managed network policies are configured for ${namespaces} namespace(s). Check each namespace’s lock or Network & security for details.`));
  return badges.join("");
}

export function renderGlobalPolicySummary(element, controls) {
  // Older HTML may still be served during a rolling upgrade.
  if (!element) return;
  element.innerHTML = globalPolicyBadges(controls);
  element.hidden = !element.childElementCount;
}

export function sandboxPolicyBadges(sandbox, controls = {}) {
  const badges = [];
  const owner = controls.users?.[sandbox.owner];
  if (restricted(owner)) badges.push(badge("User restrictions", restrictionDetails(owner, "The owner’s")));
  if (sandbox.admin_control?.disabled) badges.push(badge("VM restrictions", `This sandbox’s access and startup are blocked. ${sandbox.admin_control.reason || ""}`.trim()));
  const namespace = controls.namespaces?.[sandbox.namespace_key];
  if (namespacePolicy(namespace) || sandbox.namespace_locked) {
    const details = [];
    if (namespace?.creation_disabled || sandbox.namespace_locked) details.push("No one can create additional sandboxes in this namespace.");
    if (namespace?.network_policy != null) details.push("An administrator-managed Kubernetes network policy is configured. Check Network & security for its applied status.");
    badges.push(badge("Namespace restrictions", details.join(" ")));
  }
  return badges.length ? `<div class="admin-policy-badges" aria-label="Administrator restrictions for this sandbox">${badges.join("")}</div>` : "";
}
