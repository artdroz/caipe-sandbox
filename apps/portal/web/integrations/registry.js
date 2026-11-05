import { icon } from "../icons.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

export function securitySections(definitions, row) {
  return (row.control_panels || []).filter(item=>item.category==="security").flatMap(descriptor=>{
    const integration=definitions.find(item=>item.id===descriptor.id);
    return (integration?.securitySections || []).map(section=>({...section,integration,descriptor}));
  }).sort((a,b)=>a.order-b.order);
}

export function integrationRegistry(definitions) {
  const entries = new Map();
  for (const entry of definitions) {
    if (entries.has(entry.id)) throw new Error("Integration IDs must be unique");
    entries.set(entry.id,entry);
  }
  return {
    async openSecurity(dialog, requestFor, row) {
      const token=Symbol();dialog.panelSession=token;
      const sections=securitySections([...entries.values()],row);
      if(!sections.length)throw new Error("Network & security controls are unavailable for this micro VM.");
      const integrations=[...new Set(sections.map(item=>item.integration))];
      dialog.querySelector("[data-integration-title]").textContent=`Network & security · ${row.title}`;
      dialog.querySelector("[data-integration-logo]").innerHTML=icon("shield");
      const content=dialog.querySelector("[data-integration-content]");
      content.innerHTML=sections.map((section,index)=>`<details class="security-section" ${index===0 ? "open" : ""}><summary><span><strong>${esc(section.title)}</strong></span><span class="security-powered">Powered by ${icon(section.descriptor.icon)}${esc(section.descriptor.title)}</span></summary><div data-security-slot="${esc(section.integration.id)}/${esc(section.id)}"></div></details>`).join("")+`<details class="security-advanced"><summary>${icon("code")}Advanced<span>Native configuration & differences</span></summary>${integrations.map(item=>`<div class="security-native policy-panel" data-security-slot="${esc(item.id)}/reference"></div>`).join("")}</details>`;
      const controllers=[];
      const close=()=>{if(controllers.every(controller=>!controller?.canClose || controller.canClose()))dialog.close();};
      dialog.querySelector("[data-integration-close]").onclick=close;
      dialog.oncancel=event=>{event.preventDefault();close();};
      dialog.showModal();
      await Promise.all(integrations.map(async integration=>{
        const slots=Object.fromEntries([...content.querySelectorAll("[data-security-slot]")].filter(item=>item.dataset.securitySlot.startsWith(integration.id+"/")).map(item=>[item.dataset.securitySlot.split("/")[1],item]));
        try { controllers.push(await integration.mountSecurity(dialog,requestFor(integration.id),row,slots)); }
        catch(error) { if(dialog.panelSession===token)slots[integration.securitySections[0].id].innerHTML=`<p class="ws-message error" role="alert">${esc(error.message)}</p>`; }
      }));
    },
    async openPanel(id, dialog, request, row) {
      const entry = entries.get(id);
      if (!entry?.openPanel) throw new Error("This integration control panel is unavailable");
      const descriptor = row.control_panels?.find(item=>item.id===id);
      if (!descriptor) throw new Error("This micro VM does not expose that integration");
      dialog.querySelector("[data-integration-title]").textContent = `${descriptor.title} · ${row.title}`;
      dialog.querySelector("[data-integration-logo]").innerHTML = icon(descriptor.icon);
      return entry.openPanel(dialog,request,row);
    },
    mountCreation(root, profile, changed) {
      const controllers=[];
      const descriptors=(profile?.integrations || []).filter(item=>item.creation);
      root.hidden=!descriptors.length;
      root.innerHTML=descriptors.map(item=>`<details class="integration-creation" data-creation-integration="${esc(item.id)}"><summary>${icon(item.icon)}<strong>${esc(item.title)}</strong></summary><div data-integration-creation-body></div></details>`).join("");
      for (const descriptor of descriptors) {
        const section=[...root.querySelectorAll("[data-creation-integration]")].find(item=>item.dataset.creationIntegration===descriptor.id);
        const body=section.querySelector("[data-integration-creation-body]");
        const entry=entries.get(descriptor.id);
        if (entry?.mountCreation) controllers.push({id:descriptor.id,section,controller:entry.mountCreation(body,descriptor.creation,changed)});
        else body.innerHTML='<p class="hint">Uses profile defaults. This portal does not include an editor for this integration.</p>';
      }
      const invalid = event => {
        let parent=event.target.parentElement;
        while (parent && parent!==root) { if(parent.tagName==="DETAILS") parent.open=true; parent=parent.parentElement; }
      };
      root.addEventListener("invalid",invalid,true);
      return {
        read() {
          const result={};
          for (const {id,section,controller} of controllers) {
            try { const configuration=controller.read(); if(configuration) result[id]=configuration; }
            catch(error) { section.open=true; throw error; }
          }
          return result;
        },
        dispose() {
          root.removeEventListener("invalid",invalid,true);
          for (const {controller} of controllers) controller.dispose?.();
        },
      };
    },
  };
}
