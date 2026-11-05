import { icon } from "./icons.js";

const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

export const failedCreation = sandbox => sandbox?.operation?.kind === "create" && sandbox.operation.state === "needs_attention";

export function deletionConfirmation(sandbox) {
  return failedCreation(sandbox)
    ? `Cancel creation of ${sandbox.title}? The portal checks for existing runtime resources first. Any micro VM already created by this request will be deleted with its persistent disk.`
    : `Delete ${sandbox.title} and its persistent disk claim? Recovery of retained storage requires platform help.`;
}

export function runtimeError(sandbox, {status = false} = {}) {
  const pending = sandbox.operation?.state === "needs_attention";
  if (sandbox.state !== "Error" && !pending) return "";
  const key = `${sandbox.namespace}/${sandbox.id}/${sandbox.uid}`;
  const heading = pending && sandbox.operation.kind === "create" ? "Creation needs attention" : "Needs attention";
  const message = pending ? sandbox.operation.error || sandbox.message : sandbox.message;
  const [explanation, ...diagnostics] = String(message || "").split("\n\n");
  return `<details class="runtime-error${status ? " sandbox-status" : ""}" data-error-key="${escape(key)}">
    <summary>${icon("warning")}<strong${status ? ' data-status-message' : ""}>${status ? heading : "Error details"}</strong>${status ? '<span class="status-details-label">Error details</span>' : ""}${icon("chevron")}</summary>
    <div class="runtime-error-body"><div class="runtime-error-toolbar"><span>${escape(sandbox.reason || "Sandbox error")}</span><button class="secondary" type="button" data-action="copy-error" data-id="${escape(sandbox.id)}">${icon("copy")}<span>Copy error</span></button></div>
    ${pending && explanation ? `<p class="operation-error-explanation">${escape(explanation)}</p>` : ""}
    <pre tabindex="0" aria-label="Full error message" ${pending && !diagnostics.length ? "hidden" : ""}>${escape((pending && diagnostics.length ? diagnostics.join("\n\n") : message) || "No additional error details are available.")}</pre><p role="status" hidden></p></div>
  </details>`;
}

export function runtimeStatus(sandbox) {
  if (sandbox.state === "Error" || sandbox.operation?.state === "needs_attention") return runtimeError(sandbox, {status:true});
  const message = sandbox.state === "Running" && sandbox.message === "Waiting for sandbox readiness" ? "micro VM ready" : sandbox.message || sandbox.state;
  return `<div class="sandbox-status" role="status">${icon("info")}<span data-status-message>${escape(message)}</span></div>`;
}

export async function copyRuntimeError(button) {
  const details = button.closest(".runtime-error");
  const text = details.querySelector("pre");
  const explanation = details.querySelector(".operation-error-explanation");
  const copy = explanation && !text.hidden ? explanation.textContent + "\n\n" + text.textContent : text.textContent;
  const status = details.querySelector("[role=status]");
  status.hidden = false;
  try {
    await navigator.clipboard.writeText(copy);
    status.textContent = "Error copied to clipboard.";
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    const target = text.hidden ? explanation : text;
    range.selectNodeContents(target);
    selection?.removeAllRanges();
    selection?.addRange(range);
    target.focus({preventScroll:true});
    status.textContent = "Clipboard unavailable. The error text is selected so you can copy it manually.";
  }
}
