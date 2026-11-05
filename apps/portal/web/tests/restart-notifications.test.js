import {test} from "node:test";
import assert from "node:assert/strict";
import {RestartNotifications} from "../restart-notifications.js";

function setup({permission = "default", permissionResult = "granted", enabled, hidden = true} = {}) {
  const listeners = new Map(), sent = [], activated = [], values = new Map();
  let requests = 0, focused = 0;
  class Notification {
    static permission = permission;
    static async requestPermission() { requests++; this.permission = permissionResult; return permissionResult; }
    constructor(title, options) { Object.assign(this, {title, options}); sent.push(this); }
    close() { this.closed = true; }
  }
  if (typeof enabled === "boolean") values.set("portal-restart-notifications", String(enabled));
  const listen = (type, handler) => listeners.set(type, handler);
  const env = {
    Notification, isSecureContext:true, addEventListener:listen, focus:()=>focused++,
    document:{title:"Portal", hidden, hasFocus:()=>true, addEventListener:listen},
    localStorage:{getItem:key=>values.get(key), setItem:(key,value)=>values.set(key,value)},
  };
  const notifications = new RestartNotifications({env, activate:key=>activated.push(key)});
  return {env, notifications, listeners, sent, activated, requests:()=>requests, focused:()=>focused};
}

test("restart events never request permission on their own", () => {
  const {env,notifications,sent,requests}=setup();
  notifications.warn("shell",310);
  assert.equal(requests(),0);
  assert.equal(sent.length,0);
  assert.match(env.document.title,/Portal restarting/);
});

test("the first terminal requests permission once and enables notifications by default", async () => {
  const {notifications,requests,env,sent}=setup();
  await notifications.firstTerminalCreated();
  await notifications.firstTerminalCreated();
  assert.equal(requests(),1);
  assert.equal(notifications.state().enabled,true);
  assert.equal(env.localStorage.getItem("portal-restart-notifications"),"true");
  notifications.warn("first",180);
  assert.equal(sent.length,1);
});

test("an explicit opt-out survives terminal creation and previously granted permission", async () => {
  const {notifications,requests}=setup({permission:"granted",enabled:false});
  await notifications.firstTerminalCreated();
  assert.equal(notifications.state().enabled,false);
  assert.equal(requests(),0);
});

test("previously granted permission enables the first terminal without another prompt", async () => {
  const {notifications,requests}=setup({permission:"granted"});
  await notifications.firstTerminalCreated();
  assert.equal(notifications.state().enabled,true);
  assert.equal(requests(),0);
});

test("dismissing or denying the first prompt does not repeat it for later shells", async () => {
  for (const permissionResult of ["default","denied"]) {
    const {notifications,requests,env}=setup({permissionResult});
    await notifications.firstTerminalCreated();
    await notifications.firstTerminalCreated();
    assert.equal(requests(),1);
    assert.equal(notifications.state().enabled,false);
    assert.equal(env.localStorage.getItem("portal-restart-notifications"),"false");
  }
});

test("a delayed permission response cannot undo a newer opt-out from another tab", async () => {
  const {notifications,env,listeners}=setup();
  let grant;
  env.Notification.requestPermission=()=>new Promise(resolve=>{grant=resolve;});
  const enabling=notifications.firstTerminalCreated();
  env.localStorage.setItem("portal-restart-notifications","false");
  listeners.get("storage")({key:"portal-restart-notifications"});
  env.Notification.permission="granted";
  grant("granted");
  await enabling;
  assert.equal(notifications.state().enabled,false);
});

test("the bell reuses an outstanding first-terminal permission request", async () => {
  const {notifications,env}=setup();
  let grant, requests=0;
  env.Notification.requestPermission=()=>{requests++;return new Promise(resolve=>{grant=resolve;});};
  const first=notifications.firstTerminalCreated();
  const bell=notifications.toggle();
  assert.equal(requests,1);
  env.Notification.permission="granted";
  grant("granted");
  await Promise.all([first,bell]);
  assert.equal(notifications.state().enabled,true);
});

test("user opt-in requests permission and sends one background alert across sessions", async () => {
  const {notifications,sent,requests,activated,focused}=setup();
  await notifications.toggle();
  notifications.warn("first",310);
  notifications.warn("second",309);
  notifications.warn("first",308);
  assert.equal(requests(),1);
  assert.equal(sent.length,1);
  assert.equal(sent[0].options.tag,"sandbox-portal-restart");
  assert.match(sent[0].options.body,/helpers are not rerun/);
  sent[0].onclick();
  assert.equal(focused(),1);
  assert.deepEqual(activated,["first"]);
});

test("a warning received in the foreground notifies when the user switches tabs", () => {
  const {env,notifications,listeners,sent}=setup({permission:"granted",enabled:true,hidden:false});
  notifications.warn("shell",310);
  assert.equal(sent.length,0);
  env.document.hidden=true;
  listeners.get("visibilitychange")();
  assert.equal(sent.length,1);
  listeners.get("blur")();
  assert.equal(sent.length,1);
});

test("recovering one shell retains warnings for others; the next restart can notify again", () => {
  const {env,notifications,sent}=setup({permission:"granted",enabled:true});
  notifications.warn("one",310);
  notifications.warn("two",310);
  notifications.clear("one");
  assert.match(env.document.title,/Portal restarting/);
  notifications.clear("two");
  assert.equal(env.document.title,"Portal");
  assert.equal(sent[0].closed,true);
  notifications.warn("next",310);
  assert.equal(sent.length,2);
});

test("denied permissions, unsupported browsers and insecure contexts retain title fallback", async () => {
  for (const unsupported of ["denied","missing","insecure"]) {
    const {env,notifications,sent,requests}=setup({enabled:true,permission:unsupported==="denied"?"denied":"granted"});
    if (unsupported==="missing") delete env.Notification;
    if (unsupported==="insecure") env.isSecureContext=false;
    assert.equal(notifications.state().disabled,true);
    await notifications.toggle();
    notifications.warn("shell",310);
    assert.equal(requests(),0);
    assert.equal(sent.length,0);
    assert.match(env.document.title,/Portal restarting/);
  }
});

test("blocked storage and notification failures cannot break the terminal warning", async () => {
  const {env,notifications,sent}=setup({permission:"granted",enabled:false});
  env.localStorage.setItem=()=>{throw new Error("blocked storage");};
  await notifications.toggle();
  notifications.warn("shell",310);
  sent[0].onerror();
  assert.equal(notifications.state().disabled,true);
  assert.match(env.document.title,/Portal restarting/);
  notifications.clear("shell");
  assert.equal(env.document.title,"Portal");
});

test("disabling alerts persists the choice and does not request permission again", async () => {
  const {env,notifications,sent,requests}=setup({permission:"granted",enabled:true});
  await notifications.toggle();
  notifications.warn("shell",310);
  assert.equal(env.localStorage.getItem("portal-restart-notifications"),"false");
  assert.equal(sent.length,0);
  assert.equal(requests(),0);
});

test("a late background alert describes the interruption instead of a past future deadline", () => {
  const {notifications,sent}=setup({permission:"granted",enabled:true});
  notifications.warn("shell",0);
  assert.match(sent[0].options.body,/restart interrupted terminal connections/);
  assert.doesNotMatch(sent[0].options.body,/will close at/);
});
