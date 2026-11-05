import test from "node:test";
import assert from "node:assert/strict";
import { readNetwork, editNetwork, networkForm, networkReview } from "../integrations/openshell/network-form.js";
import { candidatePolicy, policyPanel } from "../integrations/openshell/panel.js";

const document = () => ({network_policies:{github:{name:"GitHub",binaries:[{path:"/usr/bin/curl"}],endpoints:[{host:"api.github.com",port:443,protocol:"rest",access:"NETWORK_ACCESS_PRESET_READ_ONLY",enforcement:"NETWORK_ENFORCEMENT_MODE_ENFORCE"}]}}});
const target = field => ({networkRule:"github",endpoint:"0",networkField:field});

test("form edits preserve advanced native fields, middleware and the original object", () => {
  const original=document();
  original.network_policies.github.endpoints[0].allowed_ips=["203.0.113.0/24"];
  original.network_policies.github.endpoints[0].deny_rules=[{method:"POST",path:"/admin/*"}];
  original.network_middlewares={private_extension:{opaque:{options:[1,true,"value"]}}};
  const copy=structuredClone(original);
  const edited=editNetwork(original,target("host"),"github.example.com");
  assert.deepEqual(original,copy);
  assert.deepEqual(edited.network_middlewares,original.network_middlewares);
  assert.deepEqual(edited.network_policies.github.endpoints[0].deny_rules,original.network_policies.github.endpoints[0].deny_rules);
  assert.deepEqual(edited.network_policies.github.endpoints[0].allowed_ips,["203.0.113.0/24"]);
  const roundTrip=readNetwork(JSON.stringify(edited));
  assert.deepEqual(roundTrip,edited);
  const base={version:1,filesystem:{read_only:["/usr"]},process:{run_as_user:"1000"},...original};
  assert.deepEqual(candidatePolicy({base_policy:base},JSON.stringify(edited)).filesystem,base.filesystem);
});

test("adding and removing rules, destinations and binaries edits the native arrays", () => {
  let value=editNetwork(document(),{networkAction:"add-rule"});
  value=editNetwork(value,{networkAction:"add-rule"});
  assert.deepEqual(Object.keys(value.network_policies),["github","rule-1","rule-2"]);
  value=editNetwork(value,{networkRule:"github",networkAction:"add-endpoint"});
  assert.equal(value.network_policies.github.endpoints[1].port,443);
  assert.equal(value.network_policies.github.endpoints[1].enforcement,"NETWORK_ENFORCEMENT_MODE_ENFORCE");
  value=editNetwork(value,{networkRule:"github",networkAction:"add-binary"});
  value=editNetwork(value,{networkRule:"github",binary:"1",networkField:"path"},"/usr/bin/git");
  assert.equal(value.network_policies.github.binaries[1].path,"/usr/bin/git");
  value=editNetwork(value,{networkRule:"github",endpoint:"0",networkAction:"remove-endpoint"});
  value=editNetwork(value,{networkRule:"github",binary:"0",networkAction:"remove-binary"});
  value=editNetwork(value,{networkRule:"rule-1",networkAction:"remove-rule"});
  assert.equal(value.network_policies.github.endpoints.length,1);
  assert.equal(value.network_policies.github.binaries[0].path,"/usr/bin/git");
  assert.equal(value.network_policies["rule-1"],undefined);
});

test("protocol controls respect TCP semantics and cannot erase advanced request settings", () => {
  const tcp=editNetwork(document(),target("protocol"),"tcp");
  assert.equal(tcp.network_policies.github.endpoints[0].access,undefined);
  assert.equal(tcp.network_policies.github.endpoints[0].enforcement,undefined);
  const rest=editNetwork(tcp,target("protocol"),"rest");
  assert.equal(rest.network_policies.github.endpoints[0].enforcement,"NETWORK_ENFORCEMENT_MODE_ENFORCE");
  rest.network_policies.github.endpoints[0].allowed_ips=["203.0.113.0/24"];
  assert.deepEqual(editNetwork(rest,target("protocol"),"tcp").network_policies.github.endpoints[0].allowed_ips,["203.0.113.0/24"]);
  rest.network_policies.github.endpoints[0].rules=[{method:"GET",path:"/*"}];
  assert.throws(()=>editNetwork(rest,target("protocol"),"tcp"),/advanced endpoint/);
  assert.equal(rest.network_policies.github.endpoints[0].rules[0].method,"GET");
});

test("malformed raw documents stay out of the form and keyed maps remain safe", () => {
  for (const value of ['null','[]','{"network_policies":[]}','{"network_policies":{"bad":{"endpoints":["host"]}}}']) assert.throws(()=>readNetwork(value));
  const value=readNetwork('{"network_policies":{"__proto__":{"name":"Safe","endpoints":[],"binaries":[]}}}');
  const edited=editNetwork(value,{networkRule:"__proto__",networkField:"name"},"Preserved");
  assert.equal(edited.network_policies.__proto__.name,"Preserved");
  assert.match(networkReview({network_policies:{}},edited),/Added/);
  assert.equal({}.name,undefined);
});

test("the default editor is interactive and advanced JSON is an explicit mode", () => {
  const value=document(), base={version:1,...value};
  const state={data:{base_policy:base,saved_policy:base,effective_policy:base,can_edit:true,editable:true,state:"applied"},text:JSON.stringify(value)};
  const form=policyPanel(state);
  assert.match(form,/data-network-field="host"/);
  assert.match(form,/Add destination/);
  assert.match(form,/Edit JSON/);
  assert.doesNotMatch(form,/<textarea/);
  assert.match(policyPanel({...state,mode:"json"}),/<textarea/);
  assert.match(form,/<aside class="policy-reference" aria-label="Read-only policy reference">/);
  assert.doesNotMatch(form,/<details[^>]*open/);
});

test("review describes destination and binary changes with an optional exact JSON diff", () => {
  const value=document();
  const after=editNetwork(value,target("host"),"github.example.com");
  let review=networkReview(value,after);
  assert.match(review,/Changed/);
  assert.match(review,/<del>api.github.com:443/);
  assert.match(review,/<ins>github.example.com:443/);
  assert.doesNotMatch(review,/Additional native settings changed/);
  after.network_policies.github.endpoints[0].allowed_ips=["203.0.113.0/24"];
  review=networkReview(value,after);
  assert.match(review,/Additional native settings changed/);
  const reversed=JSON.parse(JSON.stringify(value,(key,val)=>val && !Array.isArray(val) && typeof val==="object" ? Object.fromEntries(Object.entries(val).reverse()) : val));
  assert.match(networkReview(value,reversed),/No policy changes/);
});

test("rule names, endpoints and native diagnostics remain escaped", () => {
  const value=document();
  value.network_policies.github.name='<img src=x onerror="bad()">';
  value.network_policies.github.endpoints[0].host='" onfocus="bad()';
  for (const html of [networkForm(value),networkReview({},value)]) {
    assert.doesNotMatch(html,/<img|onfocus="bad\(\)"/);
    assert.match(html,/&lt;img/);
  }
  assert.doesNotMatch(networkForm(value,{editable:false}),/<input|<select|data-network-action/);
});

test("read-only references stay separate from an unapplied draft", () => {
  const saved={version:1,...document()};
  const draft=editNetwork(document(),target("host"),"draft.example.com");
  const html=policyPanel({data:{base_policy:saved,saved_policy:saved,effective_policy:saved,profile_policy:saved,can_edit:true,editable:true},text:JSON.stringify(draft),reviewing:true});
  const reference=html.slice(html.indexOf('<aside class="policy-reference"'));
  assert.match(html.slice(0,html.indexOf('<aside class="policy-reference"')),/draft.example.com/);
  assert.doesNotMatch(reference,/draft.example.com/);
  assert.match(reference,/api.github.com/);
  assert.match(reference,/saved micro VM policy with the profile/);
});
