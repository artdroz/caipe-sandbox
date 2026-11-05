const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const object = value => value && typeof value === "object" && !Array.isArray(value);
const canonical = value => JSON.stringify(value, (key, item) => object(item) ? Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))) : item);
const keys = ["filesystem","landlock","process"];

export function readStartup(text) {
  let value;
  try { value=JSON.parse(text); } catch { throw new Error("OpenShell: enter valid JSON for the creation settings."); }
  if (!object(value) || Object.keys(value).some(key=>!keys.includes(key)) || Object.values(value).some(item=>!object(item))) throw new Error("OpenShell creation settings must contain only filesystem, landlock and process objects.");
  for (const field of ["read_only","read_write"]) {
    const paths=value.filesystem?.[field];
    if (paths!==undefined && (!Array.isArray(paths) || paths.some(path=>typeof path!=="string" || !path.startsWith("/") || path.split("/").includes("..") || (field==="read_write" && /^\/+$/u.test(path))))) throw new Error("OpenShell: use absolute filesystem paths without ..; the filesystem root cannot be writable.");
  }
  for (const field of ["run_as_user","run_as_group"]) {
    const identity=value.process?.[field];
    if (identity!==undefined && identity!=="sandbox" && !(typeof identity==="string" && /^[0-9]+$/u.test(identity) && Number(identity)>=1 && Number(identity)<=4294967294)) throw new Error("OpenShell: process identity must be sandbox or a non-root numeric UID/GID.");
  }
  return value;
}

export function editStartup(policy, field, value) {
  const draft=structuredClone(policy);
  const [section,key]=field.split(".");
  if (!keys.includes(section)) throw new Error("Unknown creation setting");
  draft[section] ??= section==="filesystem" ? {include_workdir:true} : {};
  if (["read_only","read_write"].includes(key)) value=value.split("\n").map(path=>path.trim()).filter(Boolean);
  if (section==="process" && !value) delete draft[section][key];
  else draft[section][key]=value;
  return draft;
}

export function startupForm(policy) {
  const fs=policy.filesystem || {}, process=policy.process || {};
  const compatibility=policy.landlock?.compatibility || "best_effort";
  return `<p class="hint">Set at creation. Changing these settings later requires recreating the micro VM.</p>
    <div class="openshell-startup-grid">
      <label>Read-only paths<textarea data-startup-field="filesystem.read_only" rows="3" placeholder="/usr\n/etc">${esc((fs.read_only || []).join("\n"))}</textarea></label>
      <label>Writable paths<textarea data-startup-field="filesystem.read_write" rows="3" placeholder="/sandbox">${esc((fs.read_write || []).join("\n"))}</textarea></label>
    </div>
    <label class="check-label"><input type="checkbox" data-startup-field="filesystem.include_workdir" ${fs.include_workdir || !policy.filesystem ? "checked" : ""}>Allow access to the working directory</label>
    <label>Landlock compatibility<select data-startup-field="landlock.compatibility">${["hard_requirement","best_effort",...(!["hard_requirement","best_effort"].includes(compatibility) ? [compatibility] : [])].map(value=>`<option value="${esc(value)}" ${value===compatibility ? "selected" : ""}>${esc(value==="hard_requirement" ? "Required — fail if unavailable" : value==="best_effort" ? "Best effort — may run without filesystem enforcement" : value)}</option>`).join("")}</select></label>
    <div class="openshell-startup-grid">
      <label>Process user (UID)<input data-startup-field="process.run_as_user" value="${esc(process.run_as_user)}" placeholder="Platform default" autocomplete="off"></label>
      <label>Process group (GID)<input data-startup-field="process.run_as_group" value="${esc(process.run_as_group)}" placeholder="Platform default" autocomplete="off"></label>
    </div><p class="hint">One absolute path per line. User/group: sandbox or a non-root numeric ID. OpenShell validates compatibility with its runtime. Platform controls still apply.</p>`;
}

export function mountCreation(root, defaults, changed) {
  const original=structuredClone(defaults.policy || {});
  let draft=structuredClone(original), text=JSON.stringify(draft,null,2), mode="form";
  root.classList.add("openshell-creation");
  const render = () => {
    root.innerHTML=`<div class="network-editor-switch" role="group" aria-label="OpenShell creation editor"><button type="button" class="secondary" data-startup-mode="form" aria-pressed="${mode==="form"}">Settings</button><button type="button" class="secondary" data-startup-mode="json" aria-pressed="${mode==="json"}">Edit JSON</button></div>${mode==="form" ? startupForm(draft) : `<label>Native creation policy<textarea class="policy-editor" data-startup-json rows="10" spellcheck="false">${esc(text)}</textarea></label>`}<p class="hint">Network rules start from the profile and can be edited in Network &amp; security after creation.</p><p class="form-error" data-startup-error role="alert" hidden></p>`;
  };
  root.oninput=event=>{
    const input=event.target;
    if (input.hasAttribute("data-startup-json")) text=input.value;
    else if (input.dataset.startupField) {
      draft=editStartup(draft,input.dataset.startupField,input.type==="checkbox" ? input.checked : input.value);
      text=JSON.stringify(draft,null,2);
    } else return;
    root.querySelector("[data-startup-error]").hidden=true;
    changed();
  };
  root.onclick=event=>{
    const next=event.target.closest("[data-startup-mode]")?.dataset.startupMode;
    if (!next || next===mode) return;
    try { draft=readStartup(text); mode=next; render(); }
    catch(error) { const message=root.querySelector("[data-startup-error]"); message.hidden=false; message.textContent=error.message; }
  };
  render();
  return {
    read() {
      draft=readStartup(text);
      return canonical(draft)===canonical(original) ? null : {policy:draft};
    },
    dispose() { root.oninput=null; root.onclick=null; },
  };
}
