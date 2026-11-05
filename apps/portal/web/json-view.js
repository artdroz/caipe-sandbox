import { diffJson } from "diff";

const escapeHtml = (value) => value.replace(/[&<>"']/g, (character) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));

export function highlightJson(value) {
  return highlightJsonSource(JSON.stringify(value, null, 2) ?? "null");
}

export function highlightJsonSource(source) {
  const tokens = /"(?:\\.|[^"\\])*"|true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\],:]/g;
  let markup = "", position = 0;
  for (const match of source.matchAll(tokens)) {
    const token = match[0];
    const type = token.startsWith('"') ? (/^\s*:/.test(source.slice(match.index + token.length)) ? "key" : "string")
      : token === "null" ? "null" : token === "true" || token === "false" ? "boolean"
      : /^[\[\]{},:]$/.test(token) ? "punctuation" : "number";
    markup += escapeHtml(source.slice(position, match.index)) + `<span class="json-${type}">${escapeHtml(token)}</span>`;
    position = match.index + token.length;
  }
  return markup + escapeHtml(source.slice(position));
}

export function jsonBlock(value) {
  return `<div class="json-view"><div class="json-view-header"><span>JSON</span><button type="button" class="secondary" data-copy-json>Copy JSON</button></div><pre class="json-code" tabindex="0" aria-label="JSON configuration"><code>${highlightJson(value)}</code></pre></div>`;
}

export async function copyJson(button) {
  try {
    await navigator.clipboard.writeText(button.closest(".json-view").querySelector("code").textContent);
    button.textContent = "Copied";
  } catch {
    button.textContent = "Copy unavailable";
  }
  setTimeout(() => { button.textContent = "Copy JSON"; }, 2000);
}

export function jsonDiffBlock(before, after, {beforeLabel = "Profile", afterLabel = "Effective configuration"} = {}) {
  const changes = diffJson(before, after, {timeout: 500, maxEditLength: 5000});
  if (!changes) return '<p class="hint">This comparison is too large to display here. Use Show full JSON to inspect the effective configuration.</p>';
  if (!changes.some(change => change.added || change.removed)) return '<p class="hint">No differences.</p>';
  const lines = changes.flatMap(change => {
    const kind = change.added ? "added" : change.removed ? "removed" : "unchanged";
    const prefix = change.added ? "+" : change.removed ? "−" : " ";
    return change.value.replace(/\n$/, "").split("\n").map(line => `<span class="json-diff-line json-diff-${kind}"><span class="json-diff-prefix">${prefix}</span>${highlightJsonSource(line)}</span>`);
  }).join("");
  return `<div class="json-view"><div class="json-view-header json-diff-legend"><span>JSON comparison</span><span><b class="diff-removed-label">− ${escapeHtml(beforeLabel)}</b><b class="diff-added-label">+ ${escapeHtml(afterLabel)}</b></span></div><pre class="json-code json-diff" tabindex="0" aria-label="Changes from ${escapeHtml(beforeLabel)} to ${escapeHtml(afterLabel)}"><code>${lines}</code></pre></div>`;
}
