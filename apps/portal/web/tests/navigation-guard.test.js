import test from "node:test";
import assert from "node:assert/strict";
import { TerminalNavigationGuard } from "../navigation-guard.js";
import { HostedNavigationGuard } from "../integrations/caipe/navigation.js";

test("open terminals warn on refresh; closing the last session removes the warning", () => {
  const events = new EventTarget(), notifications = [];
  const guard = new TerminalNavigationGuard(state => notifications.push(state), events);
  guard.update(0);
  assert.equal(events.dispatchEvent(new Event("beforeunload", {cancelable:true})), true);
  guard.update(1);
  assert.equal(events.dispatchEvent(new Event("beforeunload", {cancelable:true})), false);
  assert.match(notifications.at(-1).message, /1 terminal session open/);
  guard.update(1);
  assert.equal(notifications.length, 2);
  guard.update(2);
  assert.match(notifications.at(-1).message, /2 terminal sessions open/);
  guard.update(0);
  assert.equal(events.dispatchEvent(new Event("beforeunload", {cancelable:true})), true);
  assert.equal(notifications.at(-1).active, false);
});

function hosted() {
  const handlers = new Map(), confirms = [];
  const events = name => ({
    addEventListener: (type, listener) => handlers.set(`${name}:${type}`,listener),
    removeEventListener: type => handlers.delete(`${name}:${type}`),
  });
  const location = {origin:"https://portal.example.test",href:"https://portal.example.test/apps/sandbox"};
  const env = {...events("child"),location,parent:{location,document:events("document")},confirm:message => { confirms.push(message); return env.accept; }};
  const guard = new HostedNavigationGuard(env);
  const state = {active:true,title:"Leave Sandbox?",message:"Active terminal sessions"};
  return {guard,env,state,handlers,confirms};
}

function click(overrides = {}) {
  const link = {href:"https://portal.example.test/chat",target:"",hasAttribute:() => false};
  return {button:0,target:{closest:() => link},preventDefault() { this.prevented=true; },stopImmediatePropagation() { this.stopped=true; },...overrides};
}

test("the same-origin host link warning can cancel navigation without changing CAIPE", () => {
  const {guard,state,handlers,confirms}=hosted();
  guard.update({mode:"caipe"},state);
  const event=click();
  handlers.get("document:click")(event);
  assert.equal(event.prevented,true);
  assert.equal(event.stopped,true);
  assert.equal(confirms.length,1);
  const modified=click({metaKey:true});
  handlers.get("document:click")(modified);
  assert.equal(modified.prevented,undefined);
  assert.equal(confirms.length,1);
  guard.update({mode:"caipe"},{...state,active:false});
  assert.equal(handlers.size,0);
});

test("approved links continue normally and page removal cleans up host listeners", () => {
  const {guard,env,state,handlers,confirms}=hosted();
  guard.update({mode:"caipe"},state);
  env.accept=true;
  const event=click();
  handlers.get("document:click")(event);
  assert.equal(event.prevented,undefined);
  assert.equal(confirms.length,1);
  handlers.get("child:pagehide")();
  assert.equal(handlers.size,0);
});

test("the host guard leaves standalone and cross-origin parents untouched", () => {
  const {guard,env,state,handlers}=hosted();
  guard.update({mode:"oidc"},state);
  assert.equal(handlers.size,0);
  env.parent=env;
  guard.update({mode:"caipe"},state);
  assert.equal(handlers.size,0);
  env.parent={get location() { throw new DOMException("Cross origin","SecurityError"); }};
  guard.update({mode:"caipe"},state);
  assert.equal(handlers.size,0);
});
