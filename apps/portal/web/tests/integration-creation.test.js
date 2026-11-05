import test from "node:test";
import assert from "node:assert/strict";
import { integrationRegistry } from "../integrations/registry.js";
import { readStartup, editStartup, startupForm } from "../integrations/openshell/creation.js";

test("startup forms preserve untouched native settings and omitted defaults", () => {
  const original={filesystem:{read_only:["/usr"],include_workdir:false},process:{run_as_user:"sandbox"},landlock:{compatibility:"hard_requirement"}};
  const next=editStartup(original,"filesystem.read_write","/sandbox\n /tmp \n");
  assert.deepEqual(next.filesystem,{read_only:["/usr"],include_workdir:false,read_write:["/sandbox","/tmp"]});
  assert.deepEqual(next.process,original.process);
  assert.equal(original.filesystem.read_write,undefined);
  assert.deepEqual(editStartup({},"filesystem.read_only","/usr"),{filesystem:{include_workdir:true,read_only:["/usr"]}});
  assert.equal(editStartup(original,"process.run_as_user","").process.run_as_user,undefined);
  assert.deepEqual(readStartup(JSON.stringify(next)),next);
});

test("creation JSON cannot change network, driver settings or unsafe paths and identities", () => {
  for (const value of ["{", "[]", "null",'{"network_policies":{}}','{"driver_config":{}}','{"filesystem":{"read_write":["/"]}}','{"filesystem":{"read_write":["//"]}}','{"filesystem":{"read_only":["relative"]}}','{"filesystem":{"read_write":["/foo/../etc"]}}','{"process":{"run_as_user":"0"}}','{"process":{"run_as_group":"root"}}']) assert.throws(()=>readStartup(value));
  assert.deepEqual(readStartup('{"process":{"run_as_user":"sandbox","run_as_group":"1000"}}'),{process:{run_as_user:"sandbox",run_as_group:"1000"}});
  assert.doesNotMatch(startupForm({filesystem:{read_only:['<img src=x onerror="bad()">']}}),/<img/);
});

test("independent integration panels share generic routing and branding", async () => {
  const title={},logo={},calls=[];
  const dialog={querySelector:selector=>selector==="[data-integration-title]" ? title : logo};
  const definitions=["one","two"].map(id=>({id,openPanel:(...args)=>calls.push([id,...args])}));
  const registry=integrationRegistry(definitions), row={title:"Example",control_panels:definitions.map(({id})=>({id,title:id,icon:"box"}))};
  for (const item of definitions) {
    await registry.openPanel(item.id,dialog,()=>{},row);
    assert.equal(title.textContent,`${item.id} · Example`);
    assert.match(logo.innerHTML,/<svg/);
  }
  assert.deepEqual(calls.map(([id])=>id),["one","two"]);
  await assert.rejects(registry.openPanel("missing",dialog,null,row),/unavailable/);
  await assert.rejects(registry.openPanel("one",dialog,null,{control_panels:[]}),/does not expose/);
  assert.throws(()=>integrationRegistry([...definitions,definitions[0]]),/unique/);
});

test("multiple creation editors read their own values, expose validation and dispose", () => {
  const sections=new Map(), mounted=[], disposed=[], listeners=new Map();
  const root={hidden:true,addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:key=>listeners.delete(key),querySelectorAll:()=>[...sections.values()]};
  for (const id of ["one","two"]) sections.set(id,{dataset:{creationIntegration:id},open:false,querySelector:()=>({id})});
  const registry=integrationRegistry(["one","two"].map(id=>({id,mountCreation:(body,defaults,changed)=>{
    mounted.push([id,body.id,defaults]); changed();
    return {read:()=>{ if(id==="two" && fail) throw new Error("Incomplete"); return {value:id}; },dispose:()=>disposed.push(id)};
  }})));
  let fail=false, changes=0;
  const controller=registry.mountCreation(root,{integrations:["one","two"].map(id=>({id,title:id,icon:"box",creation:{seed:id}}))},()=>changes++);
  assert.equal(root.hidden,false);
  assert.equal(changes,2);
  assert.deepEqual(mounted,[["one","one",{seed:"one"}],["two","two",{seed:"two"}]]);
  assert.deepEqual(controller.read(),{one:{value:"one"},two:{value:"two"}});
  fail=true; assert.throws(()=>controller.read(),/Incomplete/);
  assert.equal(sections.get("two").open,true);
  controller.dispose();
  assert.deepEqual(disposed,["one","two"]);
  assert.equal(listeners.size,0);
  registry.mountCreation(root,{integrations:[]},()=>{});
  assert.equal(root.hidden,true);
});
