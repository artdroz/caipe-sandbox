import { icon } from "../../icons.js";
import { jsonBlock } from "../../json-view.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const object = value => value && typeof value === "object" && !Array.isArray(value);

export function readPolicy(text) {
  const value = JSON.parse(text);
  if (!object(value) || value.kind !== "NetworkPolicy" || !object(value.spec) || !Array.isArray(value.spec.egress) || value.spec.egress.some(rule=>!object(rule))) throw new Error("Provide a native NetworkPolicy with spec.egress rule objects.");
  return value;
}

export function simpleRule(rule) {
  const peer = rule.to?.[0], port = rule.ports?.[0];
  return object(rule) && rule.to?.length === 1 && rule.ports?.length === 1 && object(peer) && object(port) &&
    Object.keys(rule).every(key=>["to","ports"].includes(key)) &&
    Object.keys(peer).every(key=>["namespaceSelector","podSelector"].includes(key)) &&
    Object.keys(peer.namespaceSelector || {}).every(key=>key==="matchLabels") &&
    Object.keys(peer.namespaceSelector?.matchLabels || {}).length === 1 &&
    typeof peer.namespaceSelector.matchLabels["kubernetes.io/metadata.name"] === "string" &&
    Object.keys(peer.podSelector || {}).every(key=>key==="matchLabels") &&
    Object.keys(port).every(key=>["protocol","port"].includes(key));
}

const selector = rule => Object.entries(rule.to[0].podSelector?.matchLabels || {}).map(([key,value])=>`${key}=${value}`).join(", ");
export const ruleTitle = (rule, index) => simpleRule(rule) ? `${rule.to[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"] || "New connection"} · ${rule.ports[0].port}` : `Native Kubernetes rule ${index+1}`;

export function networkForm(policy, {editable=false, busy=false, expanded=new Set()}={}) {
  const field = (label,value,index,name,options="") => `<label class="network-field"><span>${label}</span>${editable ? `<input data-cluster-index="${index}" data-cluster-field="${name}" value="${esc(value)}" ${options} ${busy ? "disabled" : ""}>` : `<span class="network-value">${esc(value || "All Pods")}</span>`}</label>`;
  return `<div class="network-rules">${policy.spec.egress.map((rule,index)=>`<details class="network-rule" data-cluster-rule="${index}" ${expanded.has(String(index)) ? "open" : ""}><summary title="${esc(ruleTitle(rule,index))}">${esc(ruleTitle(rule,index))}</summary><div class="network-rule-body">${simpleRule(rule) ? `<div class="cluster-fields">
    ${field("Destination namespace",rule.to[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"],index,"namespace","required")}
    ${field("Port",rule.ports[0].port,index,"port",'required maxlength="15"')}
    <label class="network-field"><span>Protocol</span>${editable ? `<select data-cluster-index="${index}" data-cluster-field="protocol" ${busy ? "disabled" : ""}>${["TCP","UDP","SCTP"].map(value=>`<option ${value===(rule.ports[0].protocol || "TCP") ? "selected" : ""}>${value}</option>`).join("")}</select>` : `<span class="network-value">${esc(rule.ports[0].protocol || "TCP")}</span>`}</label>
    ${field("Destination Pod labels · key=value, key=value",selector(rule),index,"selector",'placeholder="app=api"')}
    </div>` : `${jsonBlock(rule)}<p class="hint">Native fields retained. ${editable ? "Use Edit JSON to change this rule." : "Managed by platform admins."}</p>`}
    ${editable ? `<button type="button" class="secondary network-action" data-cluster-action="remove" data-cluster-index="${index}" ${busy ? "disabled" : ""}>${icon("trash")}Remove connection</button>` : ""}</div></details>`).join("") || '<p class="hint">No additional in-cluster connections.</p>'}
    ${editable ? `<button class="secondary network-action" type="button" data-cluster-action="add" ${busy ? "disabled" : ""}>${icon("plus")}Add connection</button>` : ""}</div>`;
}

export function editPolicy(policy, target, value) {
  const result = structuredClone(policy), rules=result.spec.egress, index=Number(target.clusterIndex);
  if (target.clusterAction === "add") rules.push({to:[{namespaceSelector:{matchLabels:{"kubernetes.io/metadata.name":""}},podSelector:{matchLabels:{}}}],ports:[{protocol:"TCP",port:443}]});
  else if (target.clusterAction === "remove") rules.splice(index,1);
  else {
    const rule = rules[index];
    if (!rule || !simpleRule(rule)) throw new Error("Use JSON to edit advanced Kubernetes rules.");
    if (target.clusterField === "namespace") rule.to[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"]=value;
    if (target.clusterField === "port") {
      const numeric=/^\d+$/.test(value);
      if(numeric && (!Number.isInteger(Number(value)) || Number(value)<1 || Number(value)>65535))throw new Error("Use a port from 1 to 65535, or a Kubernetes named port.");
      rule.ports[0].port=numeric ? Number(value) : value;
    }
    if (target.clusterField === "protocol") rule.ports[0].protocol=value;
    if (target.clusterField === "selector") {
      const labels=Object.create(null);
      for (const item of value.split(",").map(v=>v.trim()).filter(Boolean)) {
        const split=item.indexOf("=");
        if(split<1) throw new Error("Use key=value pairs for Pod labels.");
        const key=item.slice(0,split).trim();
        if(Object.hasOwn(labels,key))throw new Error("Each Pod label key must appear once.");
        labels[key]=item.slice(split+1).trim();
      }
      rule.to[0].podSelector={matchLabels:labels};
    }
  }
  return result;
}
