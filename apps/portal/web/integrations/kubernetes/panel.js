import { icon } from "../../icons.js";
import { jsonBlock, jsonDiffBlock, copyJson } from "../../json-view.js";
import { readPolicy, networkForm, editPolicy, ruleTitle } from "./network-form.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

export function policyPanel(state) {
  const {data,busy,mode,message,reviewing}=state;
  const refresh=`<button type="button" class="secondary" data-cluster-action="refresh" ${busy ? "disabled" : ""}>${icon("refresh")}Refresh</button>`;
  if(!data)return `<p role="status">${esc(message || "Loading Kubernetes policies…")}</p>${refresh}`;
  const editable=data.can_edit && data.editable;
  return `<div class="policy-panel cluster-policy">
    <div class="policy-status ${data.drift ? "pending" : ""}"><strong>${data.drift ? "Saved · waiting for sync" : "Policies loaded"}</strong>${refresh}</div>
    <p class="hint">Namespace <code>${esc(data.namespace)}</code> · affects ${esc(data.scope_count)} micro VM${data.scope_count===1 ? "" : "s"}.</p>
    ${!editable ? `<p class="hint">${icon("lock")}Read only · ${esc(data.reason || "Kubernetes network policies are managed by platform admins.")}</p>` : '<p class="hint">Edit additional outbound allow rules. Other policies may also grant access; runtime boundary policies remain managed by their controllers.</p>'}
    ${message ? `<div class="ws-message error" role="alert">${esc(message)}</div>` : ""}
    ${reviewing ? `<h3>Review in-cluster network changes</h3><p class="policy-notice">Changes affect ${esc(data.scope_count)} micro VM${data.scope_count===1 ? "" : "s"} in this namespace and can close existing connections.</p><div class="network-review">${readPolicy(state.text).spec.egress.map((rule,index)=>`<p>${esc(ruleTitle(rule,index))}</p>`).join("") || '<p>No additional outbound connections.</p>'}</div><details class="policy-change-json"><summary>Inspect native JSON changes</summary>${jsonDiffBlock(data.policy,readPolicy(state.text),{beforeLabel:"Saved namespace policy",afterLabel:"Your changes"})}</details><div class="policy-actions"><button class="secondary" type="button" data-cluster-action="back">Back</button><button type="button" class="warning" data-cluster-action="apply" ${busy ? "disabled" : ""}>${icon("warning")}Apply to namespace</button></div>` : `
    ${editable ? `<div class="network-editor-switch"><button type="button" class="secondary" data-cluster-action="form" aria-pressed="${mode!=="json"}">${icon("network")}Connections</button><button type="button" class="secondary" data-cluster-action="json" aria-pressed="${mode==="json"}">${icon("code")}Edit JSON</button></div>` : ""}
    ${mode==="json" && editable ? `<label class="policy-editor-label">Native Kubernetes connection policy<textarea class="policy-editor" spellcheck="false" aria-label="Kubernetes connection policy JSON" ${busy ? "disabled" : ""}>${esc(state.text)}</textarea></label>` : networkForm(readPolicy(state.text),{editable,busy,expanded:state.expanded})}
    ${editable ? `<div class="policy-actions"><span class="hint">${state.dirty ? "Unsaved changes" : "No unsaved changes"}</span><button type="button" data-cluster-action="review" ${busy || !state.dirty ? "disabled" : ""}>${icon("file")}Review network changes</button></div>` : ""}`}
    <p class="hint">Kubernetes policies can also affect internet access. When OpenShell handles a connection, its application rules must allow the destination too.</p>
  </div>`;
}

export async function mountPolicy(dialog, request, row, slots) {
  const token=dialog.panelSession, content=slots.network;
  const state={data:null,text:"",busy:false,message:"",invalid:"",mode:"form",dirty:false,reviewing:false,expanded:new Set()};
  const current=()=>dialog.open && dialog.panelSession===token;
  const discard=()=>!state.dirty || confirm("Discard unsaved Kubernetes policy changes?");
  const render=()=>{
    if(!current())return;
    for(const rule of content.querySelectorAll("[data-cluster-rule]")) {
      if(rule.open)state.expanded.add(rule.dataset.clusterRule);else state.expanded.delete(rule.dataset.clusterRule);
    }
    content.innerHTML=policyPanel(state);
    if(state.data)slots.reference.innerHTML=`<div class="policy-reference"><p>Kubernetes · read only</p><details><summary>Effective Kubernetes NetworkPolicy objects</summary><p class="hint">${esc(state.data.detail)}</p>${jsonBlock(state.data.policies)}</details><details><summary>Saved namespace connection policy</summary>${jsonBlock(state.data.policy)}</details>${state.data.drift ? `<details><summary>Compare saved and current connection policy</summary>${jsonDiffBlock(state.data.policy,state.data.policies.find(p=>p.metadata.name===state.data.policy.metadata.name)||null)}</details>` : ""}</div>`;
  };
  const refresh=async()=>{const data=await request.read();if(!current())return;state.data=data;state.text=JSON.stringify(data.policy,null,2);state.dirty=false;state.reviewing=false;state.invalid="";};
  const perform=async action=>{state.busy=true;state.message="";render();try{await action();}catch(error){state.message=error.message;}finally{state.busy=false;render();}};
  const dirty=()=>{
    state.dirty=true;
    const button=content.querySelector('[data-cluster-action="review"]');if(button)button.disabled=false;
    const hint=content.querySelector(".policy-actions>.hint");if(hint)hint.textContent="Unsaved changes";
  };
  content.oninput=event=>{
    if(!state.data?.can_edit || !state.data.editable)return;
    if(event.target.matches(".policy-editor")){state.text=event.target.value;dirty();}
    if(event.target.matches("[data-cluster-field]")) {
      try{state.text=JSON.stringify(editPolicy(readPolicy(state.text),event.target.dataset,event.target.value),null,2);state.invalid="";dirty();}
      catch(error){state.invalid=error.message;dirty();}
    }
  };
  slots.reference.onclick=event=>{const button=event.target.closest("[data-copy-json]");if(button)void copyJson(button);};
  content.onclick=event=>{
    const button=event.target.closest("[data-cluster-action]");if(!button || button.disabled)return;
    const action=button.dataset.clusterAction;
    if(action==="refresh" && !discard())return;
    if(action!=="refresh" && !state.data?.can_edit)return;
    void perform(async()=>{
      if(action==="refresh")await refresh();
      if(action==="form"){readPolicy(state.text);state.mode="form";}
      if(action==="json")state.mode="json";
      if(action==="back")state.reviewing=false;
      if(["add","remove"].includes(action)) {const policy=editPolicy(readPolicy(state.text),button.dataset);if(action==="add")state.expanded.add(String(policy.spec.egress.length-1));state.text=JSON.stringify(policy,null,2);state.dirty=true;}
      if(action==="review") {
        if(state.invalid)throw new Error(state.invalid);
        const invalid=[...content.querySelectorAll("input")].find(field=>!field.checkValidity());
        if(invalid){invalid.closest("details").open=true;invalid.reportValidity();return;}
        readPolicy(state.text);state.reviewing=true;
      }
      if(action==="apply") {
        await request.apply({uid:state.data.uid,revision:state.data.revision,native_revision:state.data.native_revision,configuration:{policy:readPolicy(state.text)}});
        await refresh();
      }
    });
  };
  render();await perform(refresh);
  return {canClose:discard};
}
