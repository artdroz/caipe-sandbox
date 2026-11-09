import test from "node:test";
import assert from "node:assert/strict";
import {globalPolicyBadges, renderGlobalPolicySummary, sandboxPolicyBadges} from "../admin-policy-view.js";

test("older pages can refresh without a restriction-summary element", () => {
  assert.doesNotThrow(() => renderGlobalPolicySummary(null, {creation_disabled:true}));
});

test("current pages show active restrictions and clear the summary when removed", () => {
  const element = {innerHTML:"", hidden:true, get childElementCount() { return this.innerHTML ? 1 : 0; }};
  renderGlobalPolicySummary(element, {creation_disabled:true});
  assert.match(element.innerHTML, /Global restrictions/);
  assert.equal(element.hidden, false);
  renderGlobalPolicySummary(element);
  assert.equal(element.innerHTML, "");
  assert.equal(element.hidden, true);
});

test("inactive settings and announcements do not look like active restrictions", () => {
  const controls = {reason:"Old reason", announcement:{title:"Hello"}, users:{"a@example.test":{creation_disabled:false}}, namespaces:{n:{network_policy:null}}};
  assert.equal(globalPolicyBadges(controls), "");
  assert.equal(sandboxPolicyBadges({owner:"a@example.test",admin_control:{notice:{title:"Hi"}}},controls), "");
});

test("global summary counts only configured user and namespace policies", () => {
  const html = globalPolicyBadges({creation_disabled:true,users:{a:{creation_disabled:true},b:{sandboxes_disabled:true},c:{reason:"Unused"}},namespaces:{a:{creation_disabled:true},b:{network_policy:{}},c:{creation_disabled:false,network_policy:null}}});
  assert.match(html, /Global restrictions/);
  assert.match(html, /User restrictions · 2/);
  assert.match(html, /Namespace restrictions · 2/);
  assert.match(html, /existing sandboxes can keep running/);
});

test("VM badges show specific restrictions while global policy stays in the summary", () => {
  const html = sandboxPolicyBadges({owner:"owner@example.test",namespace_key:"n",admin_control:{disabled:true,reason:"VM review"}}, {sandboxes_disabled:true,reason:"Maintenance",users:{"owner@example.test":{creation_disabled:true,reason:"Account review"}},namespaces:{n:{creation_disabled:true,network_policy:{spec:{}}}}});
  for (const text of ["User restrictions","VM restrictions","Namespace restrictions","VM review","Account review","No one can create additional sandboxes","Check Network &amp; security for its applied status"]) assert.ok(html.includes(text),text);
  assert.doesNotMatch(html, /Global restrictions|Maintenance/);
  assert.equal(sandboxPolicyBadges({}, {sandboxes_disabled:true}), "");
  assert.match(html, /tabindex="0"/);
});

test("owner policies do not leak onto another creator’s VM in a shared namespace", () => {
  const html = sandboxPolicyBadges({owner:"creator@example.test",namespace_key:"shared"}, {users:{"namespace-owner@example.test":{sandboxes_disabled:true}}});
  assert.equal(html, "");
});

test("namespace locks remain visible without other admin controls and text is escaped", () => {
  assert.match(sandboxPolicyBadges({namespace_locked:true}), /Namespace restrictions/);
  const html = sandboxPolicyBadges({admin_control:{disabled:true,reason:'<img src=x onerror="bad()">'}});
  assert.match(html, /&lt;img src=x onerror=&quot;bad\(\)&quot;&gt;/);
  assert.doesNotMatch(html, /<img/);
});
