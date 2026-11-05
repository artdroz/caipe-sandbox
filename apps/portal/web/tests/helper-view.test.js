import test from "node:test";
import assert from "node:assert/strict";
import {helperButton, helperStatus, cardHelperGroups} from "../helper-view.js";

test("profile helper status is independent of consumer names", () => {
  const helper={id:"custom-login",status_available:true};
  assert.equal(helperStatus(helper,{"custom-login":"signed-in"}),"Signed in");
  assert.equal(helperStatus(helper,{"custom-login":"sign-in"}),"Not signed in");
});
test("failed probes never imply authenticated state", () => {
  const helper={id:"custom-login",status_available:true};
  assert.equal(helperStatus(helper,{"custom-login":"unknown"}),"Status unavailable");
  assert.equal(helperStatus(helper,{"custom-login":"unavailable"}),"Not installed");
  assert.equal(helperStatus(helper),"Not checked");
});
test("helpers without probes have no invented authentication status", () => {
  assert.equal(helperStatus({id:"workspace",status_available:false},{workspace:"signed-in"}),"");
});

test("card and menu helpers render the actual signed-in state with a separate status label", () => {
  const markup=helperButton({id:"claude-login",title:"Sign in to Claude",icon:"claude",status_available:true},{"claude-login":"signed-in"});
  assert.match(markup,/data-status="signed-in"/);
  assert.match(markup,/<span class="helper-title">Sign in to Claude<\/span>/);
  assert.match(markup,/<span class="helper-status">.*Signed in<\/span>/);
  assert.match(markup,/title="Sign in to Claude · Signed in"/);
});

test("unprobed helpers, unknown values and custom titles are rendered honestly and safely", () => {
  const helper={id:"custom",title:'A "custom" <helper>',icon:"terminal",status_available:false};
  assert.doesNotMatch(helperButton(helper,{custom:"signed-in"}),/class="helper-status"/);
  const unknown=helperButton({...helper,status_available:true},{custom:"unexpected"},{disabled:true,attributes:'data-helper="custom"'});
  assert.match(unknown,/data-status="unchecked"/);
  assert.match(unknown,/Not checked/);
  assert.match(unknown,/A &quot;custom&quot; &lt;helper&gt;/);
  assert.match(unknown,/data-helper="custom"/);
  assert.match(unknown,/ disabled/);
});

test("cards feature two available helpers and retain only catalog-listed saved definitions", () => {
  const helpers=[{id:"connection",script:"saved-login"},{id:"editor"},{id:"assistant"},{id:"logs"}];
  const groups=cardHelperGroups(helpers,[{id:"editor"},{id:"assistant"},{id:"new-helper"},{id:"connection"}]);
  assert.deepEqual(groups.visible.map(h=>h.id),["editor","assistant"]);
  assert.deepEqual(groups.overflow.map(h=>h.id),["connection"]);
  assert.equal(groups.overflow[0],helpers[0]);
  assert.equal(groups.overflow[0].script,"saved-login");
  assert.deepEqual(helpers.map(h=>h.id),["connection","editor","assistant","logs"]);
});

test("retired helpers disappear while newly added scripts wait for a profile update", () => {
  const saved=[{id:"codex-login"},{id:"claude-login"},{id:"omnigent-login"},{id:"workspace"},{id:"disk-usage"}];
  const configured=[{id:"codex-login"},{id:"claude-login"},{id:"omnigent-login"},{id:"new-login"}];
  const groups=cardHelperGroups(saved,configured);
  assert.deepEqual(groups.visible.map(h=>h.id),["codex-login","claude-login"]);
  assert.deepEqual(groups.overflow.map(h=>h.id),["omnigent-login"]);
  assert.deepEqual(cardHelperGroups(saved,[]),{visible:[],overflow:[]});
});

test("removed profiles retain saved helper order and small lists have no overflow", () => {
  const helpers=[{id:"one"},{id:"two"},{id:"three"}];
  assert.deepEqual(cardHelperGroups(helpers),{visible:helpers.slice(0,2),overflow:helpers.slice(2)});
  assert.deepEqual(cardHelperGroups(helpers.slice(0,1)).overflow,[]);
  assert.deepEqual(cardHelperGroups([]),{visible:[],overflow:[]});
});
