import { icon } from "../../icons.js";
import { jsonBlock, jsonDiffBlock, copyJson, highlightJsonSource } from "../../json-view.js";
import { readNetwork, networkForm, editNetwork, networkReview } from "./network-form.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const network = policy => Object.fromEntries(["network_policies", "network_middlewares"].map(key => [key, policy?.[key] || {}]));
const labels = {applied:"Applied", applying:"Applying", rejected:"Rejected", unknown:"Unable to verify", managed:"Managed by platform"};

export function candidatePolicy(data, text) {
  const value = readNetwork(text);
  return {...data.base_policy, ...network(value)};
}

function editorView(state, editable) {
  const raw = state.mode === "json";
  const disabled = state.busy ? "disabled" : "";
  return `<div class="network-editor-switch" role="group" aria-label="Network policy editor"><button type="button" class="secondary" data-policy-action="form" aria-pressed="${!raw}" ${disabled}>${icon("network")}Rules</button><button type="button" class="secondary" data-policy-action="json" aria-pressed="${raw}" ${disabled}>${icon("code")}${editable ? "Edit JSON" : "View JSON"}</button></div>
    ${!raw ? networkForm(readNetwork(state.text), {editable,busy:state.busy,expanded:state.expandedRules}) : editable ? `<label class="policy-editor-label" for="openshell-network-policy">Advanced network policy JSON</label><div class="policy-code-editor"><pre class="policy-highlight json-code" aria-hidden="true"><code>${highlightJsonSource(state.text)}</code></pre><textarea id="openshell-network-policy" class="policy-editor" spellcheck="false" maxlength="262144" ${disabled}>${esc(state.text)}</textarea></div>` : jsonBlock(readNetwork(state.text))}
    ${editable ? `<div class="policy-actions"><span class="hint">${state.dirty ? "Unsaved changes" : "No unsaved edits"}</span><button type="button" data-policy-action="review" ${state.busy || !state.dirty ? "disabled" : ""}>${icon("file")}Review changes</button></div>` : ""}`;
}

function policyReference(data, includeStartup=true) {
  const startup=Object.fromEntries(Object.entries(data.base_policy).filter(([key])=>!["network_policies","network_middlewares"].includes(key)));
  return `<aside class="policy-reference" aria-label="Read-only policy reference"><p>OpenShell <span>Read only</span></p>
    <details><summary>Effective OpenShell policy</summary><p class="hint">Includes rules supplied by attached providers. Runtime confirmation is shown above.</p>${jsonBlock(data.effective_policy)}</details>
    ${data.profile_policy ? `<details><summary>Compare with profile</summary><p class="hint">Compares the saved micro VM policy with the profile.</p>${jsonDiffBlock(data.profile_policy,data.saved_policy,{beforeLabel:"Profile policy",afterLabel:"Saved micro VM policy"})}</details>` : ""}
    ${data.drift ? `<details><summary>Compare saved and current policy</summary>${jsonDiffBlock(data.saved_policy,data.base_policy,{beforeLabel:"Saved policy",afterLabel:"Current OpenShell policy"})}</details>` : ""}
    ${includeStartup ? `<details><summary>Filesystem and process settings · set at creation</summary><p class="hint">These settings require a new sandbox.</p>${jsonBlock(startup)}</details>` : ""}</aside>`;
}

function startupView(data) {
  const {filesystem={},process={},landlock={}}=data.base_policy;
  return `<p class="hint">Set at creation · changing these settings requires a supported recreation flow.</p><dl class="security-facts">${[
    ["Read-only paths",(filesystem.read_only || []).join(", ")],
    ["Writable paths",(filesystem.read_write || []).join(", ")],
    ["Runtime user / group",`${process.run_as_user || "Runtime default"} / ${process.run_as_group || "Runtime default"}`],
    ["Requested Landlock compatibility",landlock.compatibility || "Runtime default"],
  ].map(([label,value])=>`<div><dt>${esc(label)}</dt><dd>${esc(value || "None specified")}</dd></div>`).join("")}</dl>`;
}

export function policyPanel(state, {embedded=false}={}) {
  const {data, busy, message, reviewing} = state;
  if (!data) return `<p role="status">${esc(message || "Loading OpenShell policy…")}</p>${state.failed ? `<button type="button" class="secondary" data-policy-action="refresh">${icon("refresh")}Refresh</button>` : ""}`;
  const editable = data.can_edit && data.editable;
  const disabled = busy ? "disabled" : "";
  const candidate = reviewing ? candidatePolicy(data, state.text) : null;
  return `<div class="policy-panel">
    <div class="policy-status ${esc(data.state)}" role="status">${icon(data.state === "applied" ? "openshell" : "info")}<strong>${esc(labels[data.state] || labels.unknown)}</strong><span>Policy ${esc(data.policy_version)} · active ${esc(data.active_version)}</span><button class="secondary" type="button" data-policy-action="refresh" ${disabled}>${icon("refresh")}Refresh</button></div>
    ${data.detail || message ? `<div class="ws-message ${data.state === "rejected" || state.failed ? "error" : ""}" role="alert">${icon("info")}<span>${esc(message || data.detail)}</span></div>` : ""}
    ${data.detail || state.failed && message ? `<details><summary>Policy error details</summary>${jsonBlock({error:message || data.detail})}</details>` : ""}
    ${data.reason || !data.can_edit ? `<p class="policy-notice">${esc(data.reason || "Only the micro VM creator and platform admins can edit this policy.")}</p>` : ""}
    ${data.drift ? '<p class="policy-notice">OpenShell differs from the saved policy. Review both before applying. The editor starts from the current OpenShell base policy.</p>' : ""}
    ${data.pending && data.can_edit ? `<button type="button" class="secondary" data-policy-action="retry" ${disabled}>${icon("refresh")}Check application</button>` : ""}
    <div class="policy-section-heading"><div>${!embedded || reviewing ? `<h3>${reviewing ? "Review network changes" : "Network access"}</h3>` : ""}<p class="hint">${reviewing ? "These changes have not been applied." : "Choose which binaries can reach each destination. Changes are saved for this micro VM."}</p></div>${editable && data.profile_policy ? `<button type="button" class="secondary" data-policy-action="reset" ${disabled}>Reset network to profile</button>` : ""}</div>
    ${reviewing ? `<div class="network-review">${networkReview(network(data.base_policy), network(candidate))}</div><details class="policy-change-json"><summary>Inspect JSON diff</summary>${jsonDiffBlock(network(data.base_policy), network(candidate), {beforeLabel:"Current OpenShell policy", afterLabel:"Your changes"})}</details><p class="policy-notice">Applying network changes can close existing connections and streams. Clients may need to reconnect. Platform restrictions continue to apply.</p><div class="policy-actions"><button class="secondary" type="button" data-policy-action="back" ${disabled}>Back to editing</button><button class="warning" type="button" data-policy-action="apply" ${disabled}>${icon("warning")}Apply policy</button></div>` : editorView(state,editable)}
    ${embedded ? "" : policyReference(data)}
  </div>`;
}

export async function openPolicyPanel(dialog, request, row, slots=null) {
  const token = slots ? dialog.panelSession : Symbol();
  if(!slots)dialog.panelSession = token;
  const content = slots?.network || dialog.querySelector("[data-integration-content]");
  const state = {data:null, text:"", mode:"form", expandedRules:new Set(), busy:false, dirty:false, reviewing:false, message:"", failed:false};
  const current = () => dialog.panelSession === token && dialog.open;
  let refreshTimer;
  const stopRefresh = () => clearTimeout(refreshTimer);
  const scheduleRefresh = () => {
    stopRefresh();
    if (!current() || state.failed || state.dirty || state.reviewing || state.data?.state !== "applying") return;
    refreshTimer = setTimeout(() => {
      if (current() && !state.busy && !state.dirty && !state.reviewing) return perform(refresh);
    }, 5000);
  };
  dialog.addEventListener("close",stopRefresh,{once:true});
  const render = () => {
    if (!current()) return;
    for (const rule of state.data ? content.querySelectorAll(".network-rule") : []) {
      if (rule.open) state.expandedRules.add(rule.dataset.networkSection);
      else state.expandedRules.delete(rule.dataset.networkSection);
    }
    content.innerHTML = policyPanel(state,{embedded:!!slots});
    if(slots) {
      slots.startup.innerHTML=state.data ? startupView(state.data) : '<p class="hint">OpenShell settings are unavailable until the policy can be read.</p>';
      slots.reference.innerHTML=state.data ? policyReference(state.data,false) : '';
    }
    for (const rule of content.querySelectorAll(".network-rule")) rule.ontoggle = () => {
      if (!rule.isConnected || !current()) return;
      if (rule.open) state.expandedRules.add(rule.dataset.networkSection);
      else state.expandedRules.delete(rule.dataset.networkSection);
    };
    const editor = content.querySelector(".policy-editor");
    if (editor) editor.onscroll = () => {
      const preview = content.querySelector(".policy-highlight");
      preview.scrollTop = editor.scrollTop; preview.scrollLeft = editor.scrollLeft;
    };
  };
  const discard = () => !state.dirty || confirm("Discard unsaved policy changes?");
  const refresh = async () => {
    const data = await request.read();
    if (!current()) return;
    state.data = data;
    state.text = JSON.stringify(network(data.pending ? data.saved_policy : data.base_policy), null, 2);
    state.dirty = false; state.reviewing = false;
  };
  const perform = async action => {
    stopRefresh();
    state.busy = true; state.message = ""; state.failed = false; render();
    try { await action(); }
    catch (error) { state.message = error.message; state.failed = true; }
    finally { state.busy = false; render(); scheduleRefresh(); }
  };
  if(!slots) {
    dialog.querySelector("[data-integration-close]").onclick = () => { if (discard()) dialog.close(); };
    dialog.oncancel = event => { if (!discard()) event.preventDefault(); };
  } else slots.reference.onclick=event=>{const button=event.target.closest("[data-copy-json]");if(button)void copyJson(button);};
  const dirty = () => {
    stopRefresh();
    state.dirty = true;
    const review = content.querySelector('[data-policy-action="review"]');
    if (review) review.disabled = false;
    const hint = content.querySelector(".policy-actions .hint");
    if (hint) hint.textContent = "Unsaved changes";
  };
  content.oninput = event => {
    const field = event.target;
    if (field.matches(".policy-editor")) {
      state.text = field.value;
      content.querySelector(".policy-highlight code").innerHTML = highlightJsonSource(state.text);
      dirty();
    } else if (field.matches("[data-network-field]")) {
      try {
        state.text = JSON.stringify(editNetwork(readNetwork(state.text),field.dataset,field.value),null,2);
        dirty();
        if (field.dataset.networkField === "name") for (const title of content.querySelectorAll("[data-network-title]")) if (title.dataset.networkTitle === field.dataset.networkRule) title.textContent = title.title = field.value || field.dataset.networkRule;
        if (field.dataset.networkField === "protocol") {
          const {networkRule,endpoint} = field.dataset;
          render();
          [...content.querySelectorAll('[data-network-field="protocol"]')].find(el=>el.dataset.networkRule===networkRule && el.dataset.endpoint===endpoint)?.focus();
        }
      } catch (error) { state.message=error.message; state.failed=true; render(); }
    }
  };
  content.onclick = event => {
    const copy = event.target.closest("[data-copy-json]");
    if (copy) { void copyJson(copy); return; }
    const change = event.target.closest("[data-network-action]");
    if (change && !change.disabled) {
      event.preventDefault();
      const previous = readNetwork(state.text);
      const next = editNetwork(previous,change.dataset);
      if (change.dataset.networkAction === "add-rule") state.expandedRules.add(Object.keys(next.network_policies).find(key=>!Object.hasOwn(previous.network_policies || {},key)));
      state.text = JSON.stringify(next,null,2);
      dirty(); render();
      const fields = [...content.querySelectorAll("[data-network-field]")];
      const action = change.dataset.networkAction;
      const sameRule = element => action.endsWith("-rule") || element.dataset.networkRule===change.dataset.networkRule;
      const fieldName = action==="add-rule" ? "name" : action==="add-binary" ? "path" : "host";
      const focus = action.startsWith("add-")
        ? fields.filter(field=>sameRule(field) && field.dataset.networkField===fieldName).at(-1)
        : [...content.querySelectorAll("[data-network-action]")].find(button=>sameRule(button) && button.dataset.networkAction===action.replace("remove-","add-"));
      focus?.focus();
      return;
    }
    const button = event.target.closest("[data-policy-action]");
    if (!button || button.disabled) return;
    const action = button.dataset.policyAction;
    if (action === "refresh" && !discard()) return;
    if (action === "back") { state.reviewing = false; render(); return; }
    if (action === "review" && state.mode === "form") {
      const invalid = [...content.querySelectorAll("input,select")].find(field=>!field.checkValidity());
      if (invalid) {
        const rule = invalid.closest(".network-rule");
        if (rule) { rule.open=true; state.expandedRules.add(rule.dataset.networkSection); }
        invalid.reportValidity(); return;
      }
    }
    void perform(async () => {
      if (action === "form") { readNetwork(state.text); state.mode="form"; }
      if (action === "json") state.mode="json";
      if (action === "refresh") await refresh();
      if (action === "reset") { state.text = JSON.stringify(network(state.data.profile_policy), null, 2); state.dirty = true; state.reviewing = true; }
      if (action === "review") { candidatePolicy(state.data, state.text); state.reviewing = true; }
      if (["apply", "retry"].includes(action)) {
        const draft = state.text;
        try {
          if (action === "retry") await request.retry();
          else await request.apply({uid:state.data.uid, revision:state.data.revision, native_revision:state.data.native_revision, configuration:{policy:candidatePolicy(state.data, state.text)}});
        } catch (error) {
          await refresh().catch(() => {});
          if (action === "apply" && !state.data?.pending) {
            state.text = draft; state.dirty = true; state.reviewing = false;
          }
          throw error;
        }
        await refresh();
      }
    });
  };
  if(!slots)dialog.showModal();
  render();
  await perform(refresh);
  return {canClose:discard};
}
