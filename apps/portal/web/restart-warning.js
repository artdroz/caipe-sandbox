import {icon} from "./icons.js";

const escape = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

export function restartWarning(message, key = "") {
  if (!message) return "";
  const text = escape(message);
  return `<span class="restart-warning" tabindex="0" role="img" aria-label="${text}" data-restart-key="${escape(key)}">${icon("warning")}<span>Shell will restart</span><span class="field-tooltip" aria-hidden="true">${text}</span></span>`;
}
