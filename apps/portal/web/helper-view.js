import {icon} from "./icons.js";

const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = {"signed-in":"Signed in", "sign-in":"Not signed in", unavailable:"Not installed", unknown:"Status unavailable", unchecked:"Not checked"};

function helperState(helper, states) {
  if (!helper.status_available) return "";
  return Object.hasOwn(labels, states?.[helper.id]) ? states[helper.id] : "unchecked";
}

export function helperStatus(helper, states = {}) {
  return labels[helperState(helper, states)] || "";
}

export function cardHelperGroups(helpers, configured) {
  const order = new Map((configured || helpers).map((helper, index) => [helper.id, index]));
  const available = configured ? helpers.filter(helper => order.has(helper.id)) : helpers;
  const sorted = [...available].sort((a, b) => order.get(a.id) - order.get(b.id));
  return {visible: sorted.slice(0, 2), overflow: sorted.slice(2)};
}

export function helperButton(helper, states, {attributes = "", disabled = false} = {}) {
  const state = helperState(helper, states);
  const status = labels[state] || "";
  return `<button type="button" class="secondary profile-helper" data-status="${state}" title="${escape(helper.title + (status ? ` · ${status}` : ""))}" ${attributes} ${disabled ? "disabled" : ""}>${icon(helper.icon)}<span class="helper-title">${escape(helper.title)}</span>${status ? `<span class="helper-status"><i aria-hidden="true"></i>${status}</span>` : ""}</button>`;
}
