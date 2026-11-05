import { icon } from "../../icons.js";

const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const object = value => value && typeof value === "object" && !Array.isArray(value);
const sorted = value => Array.isArray(value) ? value.map(sorted) : object(value) ? Object.fromEntries(Object.keys(value).sort().map(key => [key, sorted(value[key])])) : value;
const equal = (a,b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));
const protocols = [["","Default · no request inspection"],["rest","HTTP / REST"],["tcp","TCP · connection only"],["websocket","WebSocket"],["graphql","GraphQL"],["mcp","MCP"],["json-rpc","JSON-RPC"]];
const access = [["","No access preset"],["NETWORK_ACCESS_PRESET_READ_ONLY","Read only"],["NETWORK_ACCESS_PRESET_READ_WRITE","Read / write"],["NETWORK_ACCESS_PRESET_FULL","Full access"]];
const enforcement = [["","Audit · default"],["NETWORK_ENFORCEMENT_MODE_ENFORCE","Enforce"],["NETWORK_ENFORCEMENT_MODE_AUDIT","Audit · log only"]];
const knownEndpoint = ["host","port","protocol","access","enforcement"];
const extra = (value, fields) => Object.fromEntries(Object.entries(value || {}).filter(([key]) => !fields.includes(key)));
const protocolEditable = endpoint => !Object.keys(extra(endpoint,[...knownEndpoint,"allowed_ips","ports"])).length;
const label = (options, value) => options.find(([key]) => key === value)?.[1] || String(value || options[0][1]);
const attributes = (rule, index, field, kind="endpoint") => `data-network-rule="${esc(rule)}" data-${kind}="${index}" data-network-field="${field}"`;
const disabled = busy => busy ? "disabled" : "";

export function readNetwork(text) {
  const value = JSON.parse(text);
  if (!object(value) || Object.keys(value).some(key => !["network_policies","network_middlewares"].includes(key))) throw new Error("Edit only network_policies and network_middlewares");
  for (const key of ["network_policies","network_middlewares"]) if (value[key] != null && !object(value[key])) throw new Error(`${key} must be an object`);
  for (const rule of Object.values(value.network_policies || {})) {
    if (!object(rule) || ["binaries","endpoints"].some(key => rule[key] != null && (!Array.isArray(rule[key]) || rule[key].some(item => !object(item))))) throw new Error("Each rule needs native binary and endpoint objects. Correct the JSON before opening the form.");
  }
  return value;
}

function input(title, value, attrs, editable, busy, options="") {
  return `<label class="network-field"><span>${esc(title)}</span>${editable ? `<input value="${esc(value)}" ${attrs} ${options} ${disabled(busy)}>` : `<span class="network-value">${esc(value || "Not set")}</span>`}</label>`;
}

function select(title, value, options, attrs, editable, busy) {
  const choices = options.some(([key]) => key === String(value ?? "")) ? options : [...options,[String(value),`Native value: ${value}`]];
  return `<label class="network-field"><span>${esc(title)}</span>${editable ? `<select ${attrs} ${disabled(busy)}>${choices.map(([key,text]) => `<option value="${esc(key)}" ${key===String(value ?? "") ? "selected" : ""}>${esc(text)}</option>`).join("")}</select>` : `<span class="network-value">${esc(label(options,value))}</span>`}</label>`;
}

function action(action, text, key, busy, index="", kind="endpoint", glyph="plus") {
  return `<button class="secondary network-action ${glyph === "trash" ? "network-remove" : ""}" type="button" data-network-action="${action}" data-network-rule="${esc(key)}" data-${kind}="${index}" aria-label="${esc(text)}" title="${esc(text)}" ${disabled(busy)}>${icon(glyph)}${glyph === "trash" ? "" : esc(text)}</button>`;
}

function endpointForm(endpoint, key, index, editable, busy) {
  const advanced = Object.keys(extra(endpoint,knownEndpoint)).length;
  const inspected = endpoint.protocol && endpoint.protocol !== "tcp";
  return `<div class="network-endpoint"><div class="network-destination-fields">
    ${input("Destination",endpoint.host,attributes(key,index,"host"),editable,busy,`${endpoint.allowed_ips?.length ? "" : "required"} placeholder="api.example.com"`)}
    ${input("Port",endpoint.ports ? endpoint.ports.join(", ") : endpoint.port,attributes(key,index,"port"),editable && !endpoint.ports,busy,'type="number" min="1" max="65535" required')}
    ${select("Protocol",endpoint.protocol,protocols,attributes(key,index,"protocol"),editable && protocolEditable(endpoint),busy)}
    ${inspected ? `${select("Access",endpoint.access,access,attributes(key,index,"access"),editable && !endpoint.rules?.length,busy)}${select("Mode",endpoint.enforcement,enforcement,attributes(key,index,"enforcement"),editable,busy)}` : ""}
    ${editable ? action("remove-endpoint","Remove destination",key,busy,index,"endpoint","trash") : ""}</div>
    ${!inspected ? '<p class="hint network-endpoint-note">Connection access without request inspection.</p>' : ""}
    ${advanced ? '<p class="hint network-endpoint-note">Advanced settings retained · edit in JSON.</p>' : ""}
    ${endpoint.rules?.length ? '<p class="hint network-endpoint-note">Custom request rules define access instead of a preset.</p>' : ""}
    </div>`;
}

export function networkForm(value, {editable=true,busy=false,expanded=new Set()}={}) {
  const rules = Object.entries(value.network_policies || {});
  const middlewareCount = Object.keys(value.network_middlewares || {}).length;
  return `<div class="network-rules">${rules.map(([key,rule]) => `<details class="network-rule" data-network-section="${esc(key)}" ${expanded.has(key) ? "open" : ""}>
    <summary><strong data-network-title="${esc(key)}" title="${esc(rule.name || key)}">${esc(rule.name || key)}</strong></summary>
    <div class="network-rule-body"><div class="network-rule-heading">${input("Rule name",rule.name || "",`data-network-rule="${esc(key)}" data-network-field="name"`,editable,busy,`placeholder="${esc(key)}"`)}${editable ? action("remove-rule","Remove rule",key,busy,"","endpoint","trash") : ""}</div>
    <div class="network-subheading"><h4>Destinations</h4>${editable ? action("add-endpoint","Add destination",key,busy) : ""}</div>
    ${(rule.endpoints || []).map((endpoint,index) => endpointForm(endpoint,key,index,editable,busy)).join("") || '<p class="hint">No destinations in this rule.</p>'}
    <div class="network-subheading"><h4>Allowed binaries</h4>${editable ? action("add-binary","Add binary",key,busy) : ""}</div>
    <div class="network-binaries">${(rule.binaries || []).map((binary,index) => `<div>${input("Executable path",binary.path,attributes(key,index,"path","binary"),editable,busy,'required pattern="/.*" placeholder="/usr/bin/curl"')}${editable ? action("remove-binary","Remove binary",key,busy,index,"binary","trash") : ""}</div>`).join("") || '<p class="hint">No binaries: this rule grants no executable access.</p>'}</div>
  </div></details>`).join("") || '<p class="network-empty">No sandbox network rules. Add a rule to grant access; attached providers may supply additional rules.</p>'}
    ${editable ? action("add-rule","Add rule","",busy) : ""}
    ${middlewareCount ? `<p class="hint">${middlewareCount} native middleware configuration${middlewareCount === 1 ? "" : "s"} retained. Use JSON to edit middleware.</p>` : ""}
    </div>`;
}

export function editNetwork(value, target, inputValue) {
  const next = structuredClone(value);
  next.network_policies ||= {};
  const rules = next.network_policies;
  const key = target.networkRule;
  const action = target.networkAction;
  if (action === "add-rule") {
    let number=1;
    while (Object.hasOwn(rules,`rule-${number}`)) number++;
    rules[`rule-${number}`] = {name:"New rule",endpoints:[newEndpoint()],binaries:[{path:""}]};
    return next;
  }
  if (!Object.hasOwn(rules,key)) throw new Error("Rule no longer exists");
  const rule = rules[key];
  if (action === "remove-rule") delete rules[key];
  else if (action === "add-endpoint") (rule.endpoints ||= []).push(newEndpoint());
  else if (action === "add-binary") (rule.binaries ||= []).push({path:""});
  else if (action === "remove-endpoint") rule.endpoints.splice(Number(target.endpoint),1);
  else if (action === "remove-binary") rule.binaries.splice(Number(target.binary),1);
  else if (target.networkField === "name") rule.name = inputValue;
  else if (target.networkField === "path") rule.binaries[Number(target.binary)].path = inputValue;
  else {
    const endpoint = rule.endpoints[Number(target.endpoint)];
    const field = target.networkField;
    if (!knownEndpoint.includes(field)) throw new Error("Use JSON to edit this field");
    if (field === "protocol" && !protocolEditable(endpoint)) throw new Error("Use JSON to change the protocol of an advanced endpoint");
    if (inputValue === "") delete endpoint[field];
    else endpoint[field] = field === "port" ? Number(inputValue) : inputValue;
    if (field === "protocol" && (!inputValue || inputValue === "tcp")) {
      delete endpoint.access; delete endpoint.enforcement;
    } else if (field === "protocol") {
      endpoint.access ||= "NETWORK_ACCESS_PRESET_READ_ONLY";
      endpoint.enforcement ||= "NETWORK_ENFORCEMENT_MODE_ENFORCE";
    }
  }
  return next;
}

function newEndpoint() {
  return {host:"",port:443,protocol:"rest",access:"NETWORK_ACCESS_PRESET_READ_ONLY",enforcement:"NETWORK_ENFORCEMENT_MODE_ENFORCE"};
}

const destinations = rule => (rule?.endpoints || []).map(e => `${e.host || (e.allowed_ips || []).join(", ") || "No destination"}:${e.ports?.join(",") || e.port || "?"} · ${label(protocols,e.protocol)}${e.protocol && e.protocol !== "tcp" ? ` · ${e.rules?.length ? "Custom request rules" : label(access,e.access)} · ${label(enforcement,e.enforcement)}` : ""}`).join("\n");
const binaries = rule => (rule?.binaries || []).map(b=>b.path).join("\n");
const advanced = rule => ({...extra(rule,["name","endpoints","binaries"]), endpoints:(rule?.endpoints || []).map(e=>extra(e,knownEndpoint)).filter(value=>Object.keys(value).length), binaries:(rule?.binaries || []).map(b=>extra(b,["path"])).filter(value=>Object.keys(value).length)});

export function networkReview(before, after) {
  const keys = new Set([...Object.keys(before.network_policies || {}),...Object.keys(after.network_policies || {})]);
  const changes=[];
  const row = (title,a,b) => a===b ? "" : `<div class="network-review-field"><span>${esc(title)}</span><div>${a ? `<del>${esc(a)}</del>` : ""}${b ? `<ins>${esc(b)}</ins>` : '<span class="hint">Removed</span>'}</div></div>`;
  for (const key of keys) {
    const previous = Object.hasOwn(before.network_policies || {},key) ? before.network_policies[key] : undefined;
    const next = Object.hasOwn(after.network_policies || {},key) ? after.network_policies[key] : undefined;
    if (equal(previous,next)) continue;
    const kind = !previous ? "Added" : !next ? "Removed" : "Changed";
    changes.push(`<section class="network-change"><h4><span>${kind}</span>${esc(next?.name || previous?.name || key)}</h4>${row("Rule name",previous?.name,next?.name)}${row("Destinations",destinations(previous),destinations(next))}${row("Allowed binaries",binaries(previous),binaries(next))}${!equal(advanced(previous),advanced(next)) ? '<p class="hint">Additional native settings changed. Inspect the JSON diff for the full details.</p>' : ""}</section>`);
  }
  if (!equal(before.network_middlewares || {},after.network_middlewares || {})) changes.push('<section class="network-change"><h4>Network middleware changed</h4><p class="hint">Inspect the JSON diff to review native middleware settings.</p></section>');
  return changes.join("") || '<p class="hint">No policy changes.</p>';
}
