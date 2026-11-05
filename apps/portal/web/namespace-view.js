import {icon} from "./icons.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

export function namespaceLockBadge(locked, key) {
  if (!locked) return "";
  const message = "Namespace locked — no one can create new sandboxes here";
  return `<span class="namespace-lock-icon" role="img" tabindex="0" aria-label="Namespace locked" aria-describedby="namespace-lock-${esc(key)}" title="${message}">${icon("lock")}<span id="namespace-lock-${esc(key)}" class="field-tooltip" role="tooltip">${message}</span></span>`;
}

export function namespaceOptions(namespaces, provider, modes, user) {
  const available = modes.includes("perUser") ? namespaces.filter(item => item.provider === provider && item.available) : [];
  const allowNew = modes.includes("perSandbox") || !available.length;
  return `${allowNew ? '<option value="">Create a new namespace</option>' : ""}${available.map(item => `<option value="${esc(item.name)}">${esc(item.name)}${item.owner !== user ? ` · ${esc(item.owner)}` : ""}</option>`).join("")}`;
}
