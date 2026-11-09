import { diffLines } from "diff";
import { icon } from "./icons.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const labels = {new:"New",changed:"Changed",deleted:"Deleted",applied:"Applied",recoverable:"Recoverable",invalid:"Invalid",untracked:"Untracked"};
const sourceLabel = (source, kind) => ({default:"Profile default",applied:kind === "startup" ? "Last run" : "Last applied",previous:kind === "startup" ? "Previous run" : "Previous apply"}[source]);
const actionable = file => ["new","changed","deleted","invalid","untracked"].includes(file.status);

export function fileTemplate(kind, name = "my-service.conf") {
  if (kind === "startup") return '#!/bin/bash\nset -e\n\nmkdir -p "$HOME/projects"\n';
  const program = name.replace(/\.conf$/, "");
  return `[program:${program}]\ncommand=python3 -m http.server 8080\ndirectory=%(ENV_HOME)s\nautostart=true\nautorestart=true\nstopasgroup=false\nkillasgroup=false\nstopwaitsecs=5\nredirect_stderr=true\nstdout_logfile=%(ENV_SANDBOX_STATE)s/logs/${program}.log\nstdout_logfile_maxbytes=1MB\nstdout_logfile_backups=1\n`;
}

export function configurationDiff(before, after) {
  const changes = diffLines(before, after, {timeout: 500, maxEditLength: 5000});
  if (!changes) return '<span class="ws-diff-same">This comparison is too large to display. Cancel to inspect the current file, or restore the selected saved version.</span>';
  return changes.map(part => `<span class="ws-diff-${part.added ? "added" : part.removed ? "removed" : "same"}">${esc(part.value)}</span>`).join("");
}

function badge(file, kind) {
  const status = file?.status || "new";
  return `<span class="ws-badge ${esc(status)}">${status === "applied" && kind === "startup" ? "Last run" : labels[status] || esc(status)}</span>`;
}

function reviewPanel(state) {
  const review = state.review;
  if (!review) return "";
  const actionNames = {start:"Start",restart:"Restart",remove:"Stop & remove",add:"Add · stays stopped",update:"Update · stays stopped"};
  return `<div class="ws-review"><span class="ws-review-symbol">${icon("settings")}</span><span class="section-kicker">REVIEW CHANGES</span><h3>Apply service configuration</h3><p class="ws-support">These operations affect background services in this sandbox.</p>
    ${review.repair ? '<div class="ws-callout">Generated configuration is missing or changed. Applying will rebuild it from your saved files.</div>' : ""}
    ${review.runtime_changed ? '<div class="ws-callout">The last apply was incomplete or Supervisor changed outside the portal. The listed services will be reloaded.</div>' : ""}
    <div class="ws-operation-list">${review.operations.map(operation => `<div class="ws-operation ${esc(operation.action)}"><span class="ws-operation-icon">${icon(operation.action === "remove" ? "power" : operation.action === "start" ? "play" : "refresh")}</span><strong>${esc(operation.name)}</strong><span>${actionNames[operation.action]}</span></div>`).join("") || `<div class="ws-empty-small">${review.errors.length ? "Fix validation errors to review service operations." : "No processes need to start, restart or stop."}</div>`}</div>
    ${review.errors.map(error => `<div class="ws-callout error">${esc(error.name)}: ${esc(error.error)}</div>`).join("")}
    <p class="ws-support">Your micro VM and terminals stay available. Process state does not establish application connectivity.</p>
    <div class="ws-review-actions"><button type="button" class="secondary" data-workspace-action="back" ${state.busy ? "disabled" : ""}>Back to files</button><button type="button" data-workspace-action="confirm-apply" ${state.busy || !review.can_apply ? "disabled" : ""}>${icon("play")}Apply ${review.operations.length ? review.operations.length + " " : ""}change${review.operations.length === 1 ? "" : "s"}</button></div></div>`;
}

function fileDetail(state) {
  const {data,kind,name,content,isNew,busy} = state;
  const disabled = busy ? "disabled" : "";
  const file = data.files[kind].find(file => file.name === name);
  const process = kind === "service" ? data.services.find(service => (service.group || service.name) === name?.replace(/\.conf$/, "")) : null;
  const result = kind === "startup" ? data.startup.find(entry => entry.name === name) : null;
  if (!name) return `<div class="ws-empty"><span>${icon(kind === "service" ? "server" : "terminal")}</span><h3>${kind === "service" ? "Your background services" : "Your startup scripts"}</h3><p>Select a file, or create your first ${kind === "service" ? "service configuration" : "script"}.</p><button type="button" data-workspace-action="new">${icon("plus")}New ${kind === "service" ? "service" : "script"}</button></div>`;
  const versions = file?.recovery_sources || [];
  const header = `<div class="ws-detail-header"><div>${isNew ? `<label class="ws-filename-label">Filename<input data-workspace-name aria-label="Filename" value="${esc(name)}" maxlength="70" ${disabled}></label>` : `<span class="section-kicker">${kind === "service" ? "SERVICE CONFIGURATION" : "STARTUP SCRIPT"}</span><h3>${esc(name)}</h3>`}</div><div class="ws-detail-actions">${badge(file,kind)}${!isNew ? `<button type="button" class="secondary icon-button" data-workspace-action="reload-file" aria-label="Reload file" title="Reload file" ${disabled}>${icon("refresh")}</button>` : ""}${versions.length ? `<details class="ws-versions"><summary>${icon("refresh")}Restore</summary><div>${versions.map(source => `<button type="button" class="secondary" data-workspace-action="read-version" data-source="${source}" ${disabled}>${sourceLabel(source,kind)}</button>`).join("")}</div></details>` : ""}</div></div>`;
  const processStrip = kind === "service" ? `<div class="ws-process-strip"><span class="ws-process-dot ${process?.statename === "RUNNING" ? "running" : ""}"></span><strong>${process ? esc(process.statename.charAt(0) + process.statename.slice(1).toLowerCase()) : "Not loaded"}</strong><span class="ws-support">${process?.pid ? `PID ${esc(process.pid)} · ` : ""}Process state</span>${process ? `<div>${["STOPPED","EXITED","FATAL"].includes(process.statename) ? `<button type="button" class="secondary" data-workspace-action="start" data-service="${esc(process.name)}" ${disabled}>${icon("play")}Start</button>` : `<button type="button" class="secondary" data-workspace-action="stop" data-service="${esc(process.name)}" ${disabled}>${icon("power")}Stop</button>`}<button type="button" class="secondary" data-workspace-action="restart" data-service="${esc(process.name)}" ${disabled}>${icon("refresh")}Restart</button><button type="button" class="secondary" data-workspace-action="logs" data-service="${esc(process.name)}" ${disabled}>${icon("logs")}Logs</button></div>` : ""}</div>` : `<div class="ws-process-strip">${icon("terminal")}<strong>${result ? result.timed_out ? "Last run timed out" : result.exit_code === 0 ? "Last run completed" : "Last run failed" : "Runs at next start"}</strong><button type="button" class="secondary" data-workspace-action="startup-logs" ${disabled}>${icon("logs")}Last startup logs</button></div>`;
  if (state.mode === "restore") {
    const version = state.restore;
    return `${header}<div class="ws-restore-header"><span class="ws-badge changed">RESTORE PREVIEW</span><h4>${sourceLabel(version.source,kind)}</h4><p>Restore this saved file. ${kind === "service" ? "Services change after you review and apply." : "The script runs on the next sandbox start."}</p><div class="ws-diff-legend"><span>− Current file</span><span>+ Saved version</span></div></div><pre class="ws-version-diff">${configurationDiff(version.current_content ?? content,version.content)}</pre><div class="ws-editor-footer"><button type="button" class="secondary" data-workspace-action="back" ${disabled}>Cancel</button><button type="button" data-workspace-action="confirm-restore" ${disabled}>${icon("refresh")}Restore file</button></div>`;
  }
  if (state.mode === "logs") return `${header}${processStrip}<div class="ws-code-heading"><span>PROCESS OUTPUT</span><button type="button" class="secondary" data-workspace-action="back">Back to configuration</button></div><pre class="ws-log-output">${esc(state.log || "No log output available.")}</pre>`;
  if (!isNew && file?.exists === false) return `${header}${processStrip}<div class="ws-empty ws-missing"><span>${icon("file")}</span><h3>${file.status === "deleted" ? "This file was deleted" : file.status === "untracked" ? "No saved configuration file" : "A saved version is available"}</h3><p>${process ? "The loaded process keeps its current configuration until you apply changes or restart the sandbox." : "Recover a saved version to add this file back to your micro VM."}</p><div>${versions.map(source => `<button type="button" class="${source === versions[0] ? "" : "secondary"}" data-workspace-action="read-version" data-source="${source}" ${disabled}>${icon("refresh")}Restore ${sourceLabel(source,kind).toLowerCase()}</button>`).join("")}</div></div>`;
  return `${header}${processStrip}<div class="ws-code-heading"><span>${kind === "service" ? "SUPERVISOR CONFIGURATION" : "BASH SCRIPT"}</span><span>${kind === "service" ? "INI" : "BASH"}</span></div><div class="ws-code-editor"><pre aria-hidden="true" data-workspace-lines>${Array.from({length:content.split("\n").length},(_,index)=>index+1).join("\n")}</pre><textarea data-workspace-content aria-label="${kind === "service" ? "Service configuration" : "Startup script"}" spellcheck="false" maxlength="65536" ${disabled}>${esc(content)}</textarea></div><div class="ws-editor-footer"><span class="ws-unsaved">${state.dirty ? "Unsaved changes" : "Saved in persistent home"}</span><div>${!isNew ? `<button type="button" class="secondary danger" data-workspace-action="delete" ${disabled}>${icon("trash")}Delete file</button>` : ""}<button type="button" data-workspace-action="save" ${disabled}>${icon("file")}Save file</button></div></div>`;
}

export function workspacePanel(state) {
  const {data,kind,busy,message,failed} = state;
  if (!data) return `<div class="ws-loading" role="${failed ? "alert" : "status"}">${icon(failed ? "warning" : "refresh")}<p>${esc(message || "Loading micro VM configuration…")}</p></div>`;
  const disabled = busy ? "disabled" : "";
  const pending = data.files.service.filter(actionable).length;
  const needsReview = pending || data.active_drift || data.runtime_drift;
  const files = data.files[kind];
  return `<div class="ws-shell"><div class="ws-nav"><div role="group" aria-label="Configuration type">${[["service","Services","server"],["startup","Startup scripts","terminal"]].map(([key,label,glyph])=>`<button type="button" class="secondary ${kind === key ? "selected" : ""}" data-workspace-kind="${key}" aria-pressed="${kind === key}" ${disabled}>${icon(glyph)}${label}<span>${data.files[key].filter(file=>file.exists!==false).length}</span></button>`).join("")}</div><button type="button" class="secondary icon-button" data-workspace-action="refresh" aria-label="Refresh status" title="Refresh status" ${disabled}>${icon("refresh")}</button></div>
  ${message ? `<div class="ws-message ${failed ? "error" : ""}" role="${failed ? "alert" : "status"}">${icon(failed ? "warning" : "info")}<span>${esc(message)}</span></div>` : ""}
  ${data.apply_error ? `<div class="ws-message error" role="alert">${icon("warning")}${esc(data.apply_error)}</div>` : ""}
  <div class="ws-body"><aside class="ws-sidebar"><div class="ws-sidebar-heading"><span>CONFIGURATION FILES</span><button type="button" class="secondary icon-button" data-workspace-action="new" aria-label="New ${kind === "service" ? "service" : "script"}" title="New file" ${disabled}>${icon("plus")}</button></div><div class="ws-file-list">${files.map(file=>`<button type="button" class="ws-file ${state.name === file.name && !state.isNew ? "selected" : ""}" data-workspace-select="${esc(file.name)}" ${disabled}><span class="ws-file-symbol">${icon(kind === "service" ? "file" : "terminal")}</span><span><strong>${esc(file.name)}</strong>${badge(file,kind)}</span>${state.name === file.name && !state.isNew ? icon("chevron") : ""}</button>`).join("") || '<p class="ws-sidebar-empty">No files yet.<br>Create one to get started.</p>'}</div><div class="ws-sidebar-help">${icon("disk")}<strong>Persistent disk</strong><p>Files stay in your home across suspend and resume.</p><details><summary>How this works</summary><p>${kind === "service" ? "Native Supervisor files in ~/.config/sandbox/services.d/. Save, review changes, then apply." : "Bash files in ~/.config/sandbox/startup.d/ run on sandbox start and resume. A 15-second timeout per script and 60-second budget apply."} Maximum 16 files of 64 KiB per folder.</p></details></div></aside>
  <section class="ws-detail" aria-label="${state.mode === "review" ? "Review service changes" : "File editor"}">${state.mode === "review" ? reviewPanel(state) : fileDetail(state)}</section></div>
  <div class="ws-footer"><div><span class="ws-sync-dot ${needsReview ? "pending" : ""}"></span><strong>${needsReview ? pending ? pending + ` pending service change${pending === 1 ? "" : "s"}` : "Configuration needs repair" : "Service configuration applied"}</strong><span>${kind === "startup" ? "Scripts run on the next start" : "Process status is separate from application connectivity"}</span></div><button type="button" data-workspace-action="apply" ${busy || state.dirty || !needsReview ? "disabled" : ""}>${icon("settings")}Review changes${pending ? ` <span class="ws-count">${pending}</span>` : ""}</button></div></div>`;
}

export async function openWorkspace(dialog, request, row) {
  const container = dialog.querySelector("[data-workspace-content-panel]");
  const state = {data:null,kind:"service",name:null,content:"",revision:null,isNew:false,dirty:false,busy:false,message:"",failed:false,log:null,mode:"edit",review:null,restore:null};
  const render = () => {
    container.innerHTML = workspacePanel(state);
    const textarea = container.querySelector("[data-workspace-content]");
    if (textarea) textarea.onscroll = () => { container.querySelector("[data-workspace-lines]").scrollTop = textarea.scrollTop; };
  };
  const discard = () => !state.dirty || confirm("Discard unsaved file changes?");
  const freshFile = () => {
    Object.assign(state,{isNew:true,revision:null,dirty:false,mode:"edit",restore:null});
    state.name = state.kind === "startup" ? "10-startup.sh" : "my-service.conf";
    state.content = fileTemplate(state.kind,state.name);
  };
  const refresh = async () => { state.data = await request(); };
  const read = async name => {
    const file = state.data.files[state.kind].find(file=>file.name === name);
    Object.assign(state,{name,isNew:false,dirty:false,mode:"edit",content:"",revision:null});
    if (file?.exists === false) return;
    const data = await request({action:"read",kind:state.kind,name});
    Object.assign(state,{content:data.content,revision:data.revision});
  };
  const perform = async fn => {
    state.busy=true;state.failed=false;state.message="";render();
    try { await fn(); } catch (err) {
      state.message=err.message;state.failed=true;
      if (state.mode==="review") {state.mode="edit";state.review=null;await refresh().catch(()=>{});}
    } finally {state.busy=false;render();}
  };
  dialog.querySelector("[data-workspace-title]").textContent="Startup & services";
  dialog.querySelector("[data-workspace-sandbox]").textContent=row.title;
  dialog.querySelector("[data-workspace-close]").onclick=()=>{if(discard())dialog.close();};
  dialog.oncancel=event=>{if(!discard())event.preventDefault();};
  container.oninput=event=>{
    if(!event.target.matches("[data-workspace-name], [data-workspace-content]"))return;
    if(event.target.matches("[data-workspace-name]")){
      const old=state.name;state.name=event.target.value;
      if(state.isNew && state.content===fileTemplate(state.kind,old)){
        state.content=fileTemplate(state.kind,state.name);container.querySelector("[data-workspace-content]").value=state.content;
      }
    }else state.content=event.target.value;
    state.dirty=true;
    const hint=container.querySelector(".ws-unsaved");if(hint)hint.textContent="Unsaved changes";
    const review=container.querySelector('[data-workspace-action="apply"]');if(review)review.disabled=true;
    const lines=container.querySelector("[data-workspace-lines]");if(lines)lines.textContent=Array.from({length:state.content.split("\n").length},(_,index)=>index+1).join("\n");
  };
  container.onclick=event=>{
    const tab=event.target.closest("[data-workspace-kind]");
    if(tab){if(!discard())return;state.kind=tab.dataset.workspaceKind;state.mode="edit";void perform(async()=>{const first=state.data.files[state.kind][0];if(first)await read(first.name);else Object.assign(state,{name:null,dirty:false,isNew:false});});return;}
    const selected=event.target.closest("[data-workspace-select]");
    if(selected){if(!discard())return;void perform(()=>read(selected.dataset.workspaceSelect));return;}
    const button=event.target.closest("[data-workspace-action]");if(!button || button.disabled)return;
    const action=button.dataset.workspaceAction;
    if(action==="new"){if(discard()){freshFile();render();}return;}
    if(["reload-file","read-version"].includes(action) && !discard())return;
    if(action==="delete" && !confirm(`Delete ${state.name}? ${state.kind === "service" ? "The service will stop when you apply changes or restart the sandbox." : "It will not run at the next start."}`))return;
    if(action==="back"){state.mode="edit";state.restore=null;state.review=null;state.message="";render();return;}
    void perform(async()=>{
      if(action==="apply"){
        if(state.dirty)throw new Error("Save your file before reviewing service changes.");
        state.review=await request({action:"preview"});state.mode="review";return;
      }
      if(action==="confirm-apply"){
        await request({action:"apply",preview_revision:state.review.revision});state.mode="edit";state.review=null;state.message="Service configuration applied.";
      }else if(action==="read-version"){
        const version=await request({action,kind:state.kind,name:state.name,source:button.dataset.source});
        state.restore={...version,source:button.dataset.source};state.content=version.current_content ?? state.content;state.revision=version.revision;state.dirty=false;state.mode="restore";return;
      }else if(action==="confirm-restore"){
        const version=state.restore;
        await request({action:"restore",kind:state.kind,name:state.name,source:version.source,revision:version.revision,source_revision:version.source_revision});
        await refresh();await read(state.name);state.message="File restored. "+(state.kind==="service" ? "Review service changes when ready." : "It will run at the next start.");return;
      }else if(action==="reload-file"){
        await refresh();await read(state.name);state.message="Reloaded file from the micro VM.";return;
      }else if(action==="save"){
        const result=await request({action,kind:state.kind,name:state.name,content:state.content,revision:state.revision});
        Object.assign(state,{revision:result.revision,isNew:false,dirty:false});state.message=state.kind==="service" ? "Saved. Review service changes when ready." : "Saved. Runs on the next sandbox start.";
      }else if(action==="delete"){
        const recoverable=state.data.files[state.kind].find(file=>file.name===state.name)?.recovery_sources?.length;
        await request({action,kind:state.kind,name:state.name,revision:state.revision});state.dirty=false;state.content="";state.revision=null;state.mode="edit";state.message="File deleted."+(recoverable ? " Saved versions remain available in Restore." : "");
      }else if(action==="logs" || action==="startup-logs"){
        const result=await request({action,...(button.dataset.service ? {service:button.dataset.service} : {})});state.log=result.log;state.mode="logs";return;
      }else if(action!=="refresh"){
        await request({action,...(button.dataset.service ? {service:button.dataset.service} : {})});state.message="Process action requested. Refresh to check its state.";
      }
      await refresh();
      if(action==="delete" && !state.data.files[state.kind].some(file=>file.name===state.name))state.name=null;
    });
  };
  render();dialog.showModal();
  await perform(async()=>{await refresh();const first=state.data.files.service[0];if(first)await read(first.name);});
}
