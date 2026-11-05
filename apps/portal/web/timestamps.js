const esc = value => String(value).replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));

export function dateTime(value, compact = false) {
  const date = typeof value === "string" && value.trim() ? new Date(value) : null;
  if (!date || !Number.isFinite(date.getTime())) return "—";
  const full = date.toLocaleString(undefined, {year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit",timeZoneName:"short"});
  const label = compact ? date.toLocaleString(undefined, {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}) : full;
  return `<time datetime="${date.toISOString()}" title="${esc(full)}">${esc(label)}</time>`;
}

export function sandboxMetadata(sandbox) {
  return `<div class="sandbox-namespace"><span class="metadata-label">Namespace</span><code>${esc(sandbox.namespace || "—")}</code></div><div class="sandbox-footer-row"><span class="sandbox-created"><span class="metadata-label" title="When this micro VM was first allocated; unchanged by restart or resume">Created</span>${dateTime(sandbox.created_at, true)}</span><span class="machine-owner" title="Owner: ${esc(sandbox.owner || "—")}">${esc(sandbox.owner || "—")}</span></div>`;
}
