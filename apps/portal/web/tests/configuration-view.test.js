import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { sandboxConfiguration, profileDetails } from "../configuration-view.js";
import { jsonDiffBlock } from "../json-view.js";

const spec = {podTemplate:{spec:{containers:[{name:"host", image:"tools:v1"}]}}};
const profile = {id:"engineering",title:"Engineering",revision:"sha256:abc",description:"Tools for engineers",definition:{agentSandbox:{spec}}};
const data = {profile:{title:profile.title,agentSandbox:{spec}},profile_spec:spec,creation:{revision:profile.revision},desired:{apiVersion:"agents.x-k8s.io/v1beta1",kind:"Sandbox",metadata:{name:"workspace"},spec}};

test("creation profile help has an accessible tooltip and cannot submit the form", () => {
  const html = readFileSync(new URL("../../portal/static/index.html", import.meta.url), "utf8");
  assert.match(html, /<button id="profile-info"[^>]*type="button"[^>]*aria-describedby="profile-info-tooltip"/);
  assert.match(html, /id="profile-info-tooltip"[^>]*role="tooltip">This sets the initial scripts and configuration for your sandbox\.<\/span>/);
});

test("platform messages have a visible label, preview and dialog action", () => {
  const html = readFileSync(new URL("../../portal/static/index.html", import.meta.url), "utf8");
  assert.match(html, /id="global-announcement"[^>]*type="button"[^>]*aria-haspopup="dialog"/);
  assert.match(html, /class="board-label">Message from admin<\/span>/);
  assert.match(html, /id="announcement-preview" class="board-preview"/);
  assert.match(html, /class="board-expand">Read message /);
});

test("sandbox configuration shows one profile field, full configuration and a comparison action", () => {
  const markup = sandboxConfiguration(data);
  assert.match(markup, /configuration-profile-label">Profile/);
  assert.match(markup, /<strong[^>]*>Engineering<\/strong>/);
  assert.ok(markup.indexOf('class="configuration-actions"') < markup.indexOf('class="configuration-profile"'));
  assert.ok(markup.indexOf('data-compare-profile') < markup.indexOf('class="configuration-heading"'));
  assert.match(markup, /aria-describedby="configuration-profile-tooltip"/);
  assert.match(markup, /id="configuration-profile-tooltip"[^>]*role="tooltip">A profile provides the initial tools, startup scripts and configuration/);
  assert.match(markup, /Effective configuration/);
  assert.match(markup, /apiVersion/);
  assert.match(markup, /metadata/);
  assert.match(markup, /data-compare-profile aria-expanded="false"/);
  assert.match(markup, /data-profile-comparison hidden/);
  assert.doesNotMatch(markup, /<summary>|Legacy|\blegacy\b|>creation<|>desired<|>observed</);
});

test("sandboxes without a recorded profile still show their configuration", () => {
  const markup = sandboxConfiguration({...data, profile:null, creation:null});
  assert.match(markup, /Not assigned/);
  assert.match(markup, /disabled title="No profile was recorded/);
  assert.match(markup, /apiVersion/);
  assert.doesNotMatch(markup, /Legacy|\blegacy\b/);
});

test("configuration includes the details removed from the card footer", () => {
  const markup=sandboxConfiguration(data,{id:"bright-otter",title:'Tools <script>bad()</script>',owner:"engineer@example.com",namespace_owner:"owner@example.com",namespace:"sandbox-bright-otter",namespace_strategy:"perSandbox",created_at:"2026-10-01T12:00:00Z",updated_at:"2026-11-04T14:00:00Z",profile:{id:"engineering",revision:"sha256:abc"},allocation:{cpu_request_millicores:500,memory_request_mib:512}});
  assert.match(markup,/configuration-metadata/);
  assert.match(markup,/datetime="2026-10-01T12:00:00.000Z"/);
  assert.match(markup,/datetime="2026-11-04T14:00:00.000Z"/);
  for(const value of ["bright-otter","engineer@example.com","sandbox-bright-otter","owner@example.com","0.5 cores","0.5 GiB memory","sha256:abc"]) assert.ok(markup.includes(value));
  assert.match(markup,/Tools &lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(markup,/<script>/);
});

test("configuration offers refresh to everyone and sync only when authorized and supported", () => {
  const readonly = sandboxConfiguration(data);
  assert.match(readonly, /data-refresh-configuration><svg[^>]*aria-hidden="true"/);
  assert.match(readonly, /<span>Refresh status<\/span>/);
  assert.doesNotMatch(readonly, /data-sync-configuration/);
  const managed = sandboxConfiguration({...data,can_sync:true});
  assert.match(managed, /class="configuration-sync warning"/);
  assert.match(managed, /data-sync-configuration[^>]*><svg[^>]*aria-hidden="true"/);
  assert.match(managed, /<span>Sync configuration<\/span>/);
  assert.doesNotMatch(managed, /configuration-sync-confirmation|data-apply-sync|data-cancel-sync/);
});

test("metadata drift is visible even when the native spec is unchanged", () => {
  const markup = sandboxConfiguration({...data,configuration_drift:true,desired:{...data.desired,metadata:{labels:{profile:"engineering"}}},native_configuration:{spec,metadata:{labels:{profile:"changed"}}}});
  assert.match(markup, /<details class="sandbox-failure" open>/);
  assert.match(markup, /json-diff-removed/);
  assert.match(markup, /json-diff-added/);
  assert.match(markup, /changed/);
  assert.match(markup, /− Actual configuration/);
  assert.match(markup, /\+ Saved configuration/);
});

test("JSON comparison ignores key ordering and identifies changed values", () => {
  assert.match(jsonDiffBlock({a:1,b:2}, {b:2,a:1}), /No differences/);
  const markup = jsonDiffBlock({image:"tools:v1"}, {image:"tools:v2", runtimeClassName:"kata"});
  assert.match(markup, /json-diff-removed/);
  assert.match(markup, /json-diff-added/);
  assert.match(markup, /tools:v1/);
  assert.match(markup, /tools:v2/);
  assert.match(markup, /runtimeClassName/);
});

test("comparison escapes values and preserves array order", () => {
  const markup = jsonDiffBlock({command:["a","b"]}, {command:["b","a"], note:"</code><script>bad</script>"});
  assert.match(markup, /json-diff-added/);
  assert.match(markup, /&lt;script&gt;/);
  assert.doesNotMatch(markup, /<script>/);
});

test("selected profile details include only its description, metadata and JSON", () => {
  const markup = profileDetails(profile);
  assert.match(markup, /Tools for engineers/);
  assert.match(markup, /Profile ID/);
  assert.match(markup, /sha256:abc/);
  assert.match(markup, /agentSandbox/);
  assert.doesNotMatch(markup, /<details>|<summary>|Legacy/);
});

test("profile details explicitly identify resource controls and lifecycle restrictions", () => {
  const markup = profileDetails({...profile, definition:{...profile.definition, ui:{resources:{default:{storage:"1Gi"}}}}});
  assert.match(markup, /Editable resources/);
  assert.match(markup, /ui.resources/);
  assert.match(markup, /Disk: at creation only/);
  assert.match(markup, /API validates profile bounds/);
});

test("resource inputs use per-profile request and limit bounds", async () => {
  const {resourceInputs} = await import("../resource-controls.js");
  const size = {cpu_request_millicores:500,cpu_limit_millicores:2000,memory_request_mib:1024,memory_limit_mib:4096,workspace_gib:1};
  const bounds = Object.fromEntries(Object.keys(size).map(field=>[field,{min:100,max:5000}]));
  bounds.cpu_limit_millicores={min:500,max:2000}; bounds.workspace_gib={min:1,max:50};
  const inputs=resourceInputs(size,bounds,{});
  assert.deepEqual(inputs.find(input=>input.id==="cpu-limit"),{id:"cpu-limit",value:2,min:0.5,max:2});
  assert.deepEqual(inputs.find(input=>input.id==="workspace"),{id:"workspace",value:1,min:1,max:50});
});

test("resource inputs retain platform bounds for profiles without resource controls", async () => {
  const {resourceInputs} = await import("../resource-controls.js");
  const size = {cpu_request_millicores:500,cpu_limit_millicores:2000,memory_request_mib:1024,memory_limit_mib:4096,workspace_gib:20};
  const inputs=resourceInputs(size,undefined,{cpu_millicores:{min:100,max:4000},memory_mib:{min:256,max:8192},workspace_gib:{min:1,max:200}});
  assert.equal(inputs.find(input=>input.id==="workspace").min,1);
  assert.equal(inputs.find(input=>input.id==="cpu-limit").max,4);
});
