import test from "node:test";
import assert from "node:assert/strict";
import { securitySections } from "../integrations/registry.js";
import { networkForm, readPolicy, editPolicy } from "../integrations/kubernetes/network-form.js";
import { policyPanel } from "../integrations/kubernetes/panel.js";

const policy={apiVersion:"networking.k8s.io/v1",kind:"NetworkPolicy",metadata:{name:"portal-connections",namespace:"owned"},spec:{podSelector:{matchLabels:{component:"supervisor"}},policyTypes:["Egress"],egress:[{to:[{namespaceSelector:{matchLabels:{"kubernetes.io/metadata.name":"team-services"}},podSelector:{matchLabels:{app:"api"}}}],ports:[{protocol:"TCP",port:8443}]}]}};

test("security sections are ordered by integrations and future integrations can contribute",()=>{
  const entries=[{id:"runtime",securitySections:[{id:"network",order:10},{id:"files",order:20}]},{id:"cluster",securitySections:[{id:"network",order:30}]},{id:"future",securitySections:[{id:"audit",order:25}]}];
  const row={control_panels:entries.map(item=>({id:item.id,category:"security"}))};
  assert.deepEqual(securitySections(entries,row).map(item=>`${item.integration.id}/${item.id}`),["runtime/network","runtime/files","future/audit","cluster/network"]);
  assert.equal(securitySections(entries,{control_panels:[{id:"missing",category:"security"}]}).length,0);
});

test("engineers see rules without inputs, JSON edit or apply controls",()=>{
  const data={policy,policies:[],can_edit:false,editable:true,namespace:"owned",scope_count:2};
  const state={data,text:JSON.stringify(policy),expanded:new Set(),mode:"form"};
  const html=policyPanel(state);
  assert.match(html,/Read only|managed by platform admins/);
  assert.doesNotMatch(html,/<input|<textarea|data-cluster-action="(add|remove|review|apply|json)"/);
  assert.match(html,/team-services/);
  assert.match(policyPanel({...state,data:{...data,can_edit:true}}),/Edit JSON/);
  const review=policyPanel({...state,data:{...data,can_edit:true},reviewing:true});
  assert.match(review,/affect 2 micro VMs/);
  assert.match(review,/Apply to namespace/);
});

test("native Kubernetes edits preserve selection and do not silently replace advanced rules",()=>{
  const advanced={to:[{ipBlock:{cidr:"10.2.0.0/16"}}],ports:[{protocol:"TCP",port:443,endPort:444}]};
  const original=structuredClone(policy);original.spec.egress.push(advanced);
  const changed=editPolicy(original,{clusterIndex:0,clusterField:"port"},"9443");
  assert.deepEqual(changed.spec.podSelector,policy.spec.podSelector);
  assert.deepEqual(changed.spec.egress[1],advanced);
  assert.equal(original.spec.egress[0].ports[0].port,8443);
  assert.throws(()=>editPolicy(original,{clusterIndex:1,clusterField:"port"},"9999"),/advanced/);
  assert.match(networkForm(original),/Native fields retained/);
  for(const value of ["null","[]",'{"kind":"NetworkPolicy","spec":{"egress":[null]}}'])assert.throws(()=>readPolicy(value));
});

test("untrusted namespace and native diagnostics are escaped",()=>{
  const malicious=structuredClone(policy);malicious.spec.egress[0].to[0].namespaceSelector.matchLabels["kubernetes.io/metadata.name"]='<img src=x onerror="bad()">';
  assert.doesNotMatch(networkForm(malicious),/<img/);
  assert.match(networkForm(malicious),/&lt;img/);
});

test("numeric port overflow cannot become a null port that permits all ports",()=>{
  for(const value of ["0","65536","9".repeat(400)])assert.throws(()=>editPolicy(policy,{clusterIndex:0,clusterField:"port"},value),/65535/);
  assert.equal(editPolicy(policy,{clusterIndex:0,clusterField:"port"},"api-http").spec.egress[0].ports[0].port,"api-http");
});
