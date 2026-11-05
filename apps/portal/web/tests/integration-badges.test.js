import test from "node:test";
import assert from "node:assert/strict";
import { integrationBadges, integrationTooltip, fitIntegrationBadges } from "../integration-badges.js";

const integration = (id, layer="Runtime", state="active") => ({id,title:id,layer,state,icon:"box"});

test("narrow badge rows use logos and restore full labels when space is available", () => {
  const classes = new Set();
  const group = {clientWidth:160, children:[80,80,60].map(width=>({getBoundingClientRect:()=>({width})})),classList:{remove:name=>classes.delete(name),toggle:(name,on)=>on ? classes.add(name) : classes.delete(name)}};
  const previous = globalThis.getComputedStyle;
  globalThis.getComputedStyle = () => ({columnGap:"4px"});
  try {
    fitIntegrationBadges(group);
    assert.ok(classes.has("integration-icons-only"));
    group.clientWidth = 250;
    fitIntegrationBadges(group);
    assert.ok(!classes.has("integration-icons-only"));
  } finally { if (previous) globalThis.getComputedStyle=previous; else delete globalThis.getComputedStyle; }
});

test("badges prioritize OpenShell, Omnigent and Kata before other integrations", () => {
  const items = [integration("custom-a"),integration("kata"),integration("custom-b"),integration("omnigent"),integration("openshell")];
  const original = items.map(item=>item.id);
  const html = integrationBadges(items,{key:"vm"});
  const hidden = JSON.parse(html.match(/data-integration-items="(.*?)"/)[1].replaceAll("&quot;", '"'));
  assert.deepEqual(hidden.map(item=>item.id),["kata","custom-a","custom-b"]);
  assert.ok(html.indexOf('integration-name">openshell') < html.indexOf('integration-name">omnigent'));
  assert.deepEqual(items.map(item=>item.id),original);
  const tooltip = integrationTooltip(items,"assets/integrations");
  const positions = ["openshell","omnigent","kata","custom-a","custom-b"].map(id=>tooltip.indexOf(`integration-name">${id}`));
  assert.deepEqual(positions,[...positions].sort((a,b)=>a-b));
});

test("any integration layer renders as a compact named badge", () => {
  assert.equal(integrationBadges([]), "");
  const html = integrationBadges([integration("Custom runtime"), integration("VM", "Isolation")], {key:"sandbox"});
  assert.match(html, /Custom runtime/);
  assert.match(html, /VM · Isolation · Active/);
  assert.doesNotMatch(html, /Protected|protection-badge|integration-overflow-count/);
});

test("overflow counts only the extra badges and carries their actual statuses", () => {
  const items = [integration("Runtime"), integration("Isolation"), integration("Egress", "Network", "configured"), integration("Agent", "Workload", "unknown")];
  const html = integrationBadges(items, {key:"sandbox/123"});
  assert.match(html, /aria-label="2 more integrations">\+2<\/button>/);
  assert.match(html, /integration-overflow-sandbox%2F123/);
  assert.equal((html.match(/class="integration-badge"/g) || []).length, 2);
  const hidden = JSON.parse(html.match(/data-integration-items="(.*?)"/)[1].replaceAll("&quot;", '"'));
  assert.deepEqual(hidden.map(item=>item.id), ["Egress","Agent"]);
  const tooltip = integrationTooltip(hidden, "assets/integrations");
  assert.match(tooltip, /Network · Configured/);
  assert.match(tooltip, /Workload · Status unavailable/);
  assert.doesNotMatch(tooltip, /<button|<a |role="menu/);
});

test("unknown states never look active and untrusted labels stay escaped", () => {
  const html = integrationBadges([{...integration('<script>'),state:"surprise",detail:'A "note" <here>'}], {key:"sandbox"});
  assert.match(html, /data-state="unknown"/);
  assert.match(html, /Status unavailable/);
  assert.match(html, /&lt;script&gt;/);
  assert.match(html, /&quot;note&quot; &lt;here&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("badge images use local assets with a fallback icon", () => {
  const render = image => integrationBadges([{...integration("Custom"),image}], {key:"sandbox",assetBase:"/portal/assets/integrations"});
  assert.match(render("custom.svg"), /src="\/portal\/assets\/integrations\/custom.svg"/);
  assert.match(render("custom.svg"), /<img .*<svg/);
  for (const unsafe of ["https://example.com/icon.svg", "../icon.svg", 'x.svg" onerror="alert(1)', "data:image/svg+xml,test"])
    assert.doesNotMatch(render(unsafe), /<img/);
});
