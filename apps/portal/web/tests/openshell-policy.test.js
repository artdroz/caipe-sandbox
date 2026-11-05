import test from "node:test";
import assert from "node:assert/strict";
import { candidatePolicy, openPolicyPanel, policyPanel } from "../integrations/openshell/panel.js";

const policy = {version:1, filesystem:{read_only:["/usr"]}, process:{run_as_user:"1000"}, network_policies:{github:{endpoints:[{host:"api.github.com",port:443}]}}};
const data = {base_policy:policy, saved_policy:policy, effective_policy:policy, profile_policy:policy, can_edit:true, editable:true, state:"applied", policy_version:1, active_version:1};
const state = changes => ({data, text:JSON.stringify({network_policies:{}}), dirty:true, ...changes});

test("network edits preserve native filesystem and process configuration", () => {
  const result = candidatePolicy(data, JSON.stringify({network_policies:{}}));
  assert.deepEqual(result.filesystem, policy.filesystem);
  assert.deepEqual(result.process, policy.process);
  assert.deepEqual(result.network_policies, {});
  assert.throws(() => candidatePolicy(data, '{"filesystem":{}}'), /Edit only/);
  assert.throws(() => candidatePolicy(data, 'null'), /Edit only/);
});

test("review shows the exact network diff and requires explicit Apply", () => {
  const editing = policyPanel(state());
  assert.match(editing, /Review changes/);
  assert.doesNotMatch(editing, /data-policy-action="apply"/);
  const review = policyPanel(state({reviewing:true}));
  assert.match(review, /json-diff-removed/);
  assert.match(review, /api.github.com/);
  assert.match(review, /Apply policy/);
  assert.match(review, /close existing connections/);
});

test("read-only collaborators and global policy have no editor or apply control", () => {
  for (const restricted of [{can_edit:false}, {editable:false, reason:"A platform global policy is active"}]) {
    const view = policyPanel(state({data:{...data,...restricted}}));
    assert.doesNotMatch(view, /<textarea/);
    assert.doesNotMatch(view, /data-policy-action="review"|data-policy-action="apply"/);
    assert.match(view, /Effective OpenShell policy/);
  }
});

test("pending and failed states expose status and recovery without implying success", () => {
  const applying = policyPanel(state({data:{...data, state:"applying", active_version:1, policy_version:2, pending:true}}));
  assert.match(applying, />Applying</);
  assert.match(applying, /Check application/);
  assert.doesNotMatch(applying, />Applied</);
  const rejected = policyPanel(state({data:{...data,state:"rejected",detail:'<img src=x onerror="bad()">'}}));
  assert.match(rejected, /&lt;img/);
  assert.doesNotMatch(rejected, /<img/);
});

test("normal activation has progress without a failed action or Retry control", () => {
  const applying = policyPanel(state({dirty:false,data:{...data,state:"applying",editable:false,pending:false,policy_version:2,active_version:1,reason:"Waiting for OpenShell to activate the saved policy."}}));
  assert.match(applying, />Applying</);
  assert.match(applying, /Waiting for OpenShell/);
  assert.doesNotMatch(applying, /role="alert"|Policy error details|Check application|data-policy-action="apply"/);
});

function panelFixture(t, read) {
  const timers = new Map(), listeners = new Map(), close = {};
  t.mock.method(globalThis,"setTimeout",callback=>{const id=Symbol();timers.set(id,callback);return id;});
  t.mock.method(globalThis,"clearTimeout",id=>timers.delete(id));
  const content = {innerHTML:"",querySelectorAll:()=>[],querySelector:()=>null};
  const dialog = {
    open:false,
    querySelector:selector=>selector==="[data-integration-content]" ? content : close,
    showModal(){this.open=true;},
    addEventListener:(event,callback)=>listeners.set(event,callback),
    close(){this.open=false;listeners.get("close")?.();},
  };
  const request = {read:t.mock.fn(read),apply:t.mock.fn(),retry:t.mock.fn()};
  return {dialog,content,close,request,timers,async tick(){
    const [id,callback] = timers.entries().next().value;
    timers.delete(id);await callback();
  }};
}

test("an open applying panel observes activation without resubmitting the update", async t => {
  let current={...data,state:"applying",editable:false,pending:false,policy_version:2};
  const panel=panelFixture(t,async()=>current);
  await openPolicyPanel(panel.dialog,panel.request,{});
  assert.match(panel.content.innerHTML,/>Applying</);
  current={...current,state:"applied",editable:true,active_version:2};
  await panel.tick();
  assert.match(panel.content.innerHTML,/>Applied</);
  assert.equal(panel.request.read.mock.callCount(),2);
  assert.equal(panel.request.apply.mock.callCount(),0);
  assert.equal(panel.request.retry.mock.callCount(),0);
  assert.equal(panel.timers.size,0);
});

test("closing the control panel cancels activation polling", async t => {
  const panel=panelFixture(t,async()=>({...data,state:"applying",editable:false}));
  await openPolicyPanel(panel.dialog,panel.request,{});
  assert.equal(panel.timers.size,1);
  panel.close.onclick();
  assert.equal(panel.dialog.open,false);
  assert.equal(panel.timers.size,0);
  assert.equal(panel.request.read.mock.callCount(),1);
});

test("an old integration panel cannot poll after another panel replaces it", async t => {
  const panel=panelFixture(t,async()=>({...data,state:"applying",editable:false}));
  await openPolicyPanel(panel.dialog,panel.request,{});
  panel.dialog.panelSession=Symbol();
  await panel.tick();
  assert.equal(panel.request.read.mock.callCount(),1);
  assert.equal(panel.timers.size,0);
});

test("activation read errors stop automatic requests and leave an explicit refresh", async t => {
  let available=true;
  const panel=panelFixture(t,async()=>{
    if(!available) throw new Error("Gateway unavailable");
    return {...data,state:"applying",editable:false};
  });
  await openPolicyPanel(panel.dialog,panel.request,{});
  available=false;
  await panel.tick();
  assert.match(panel.content.innerHTML,/Gateway unavailable/);
  assert.match(panel.content.innerHTML,/data-policy-action="refresh"/);
  assert.equal(panel.timers.size,0);
  assert.equal(panel.request.apply.mock.callCount(),0);
  assert.equal(panel.request.retry.mock.callCount(),0);
});
