import test from "node:test";
import assert from "node:assert/strict";

import { sandboxConfiguration, profileDetails } from "../configuration-view.js";

test("native OpenShell configuration has a profile diff and honest resize guidance", () => {
  const spec = {template:{image:"tools@sha256:abc"},policy:{version:1}};
  const html = sandboxConfiguration({profile:{title:"Protected engineering",openShell:{spec}},profile_spec:spec,creation:{revision:"sha256:abc"},desired:{spec},capabilities:{resize:false}});
  assert.match(html, /Compare with profile/);
  assert.match(html, /does not support resizing/);
  assert.match(html, /at creation/);
  assert.doesNotMatch(html, /CPU and memory can be changed while suspended/);
});

test("protected profile details describe creation-only resource choices", () => {
  const html = profileDetails({capabilities:{resize:false,storage_source:"platform"},definition:{openShell:{spec:{}},ui:{resources:{}}}});
  assert.match(html, /CPU and memory: at creation\./);
  assert.match(html, /Disk size is set by the platform/);
  assert.doesNotMatch(html, /while suspended/);
});

test("a future backend uses the same capability UI", () => {
  const spec = {nativeSetting:true};
  const html = sandboxConfiguration({profile:{title:"Another runtime"},profile_spec:spec,desired:{spec},capabilities:{resize:false}});
  assert.match(html, /nativeSetting/);
  assert.match(html, /does not support resizing/);
  assert.doesNotMatch(html, /disabled title="No profile/);
});

test("provider drift is shown without replacing the saved effective configuration", () => {
  const saved = {image:"saved:v1"}, reported = {image:"reported:v2"};
  const html = sandboxConfiguration({desired:{spec:saved},native_configuration:{spec:reported},configuration_drift:true,observation_error:'<private>'});
  assert.match(html, /Provider settings differ/);
  assert.match(html, /saved:v1/);
  assert.match(html, /reported:v2/);
  assert.match(html, /&lt;private&gt;/);
  assert.doesNotMatch(html, /<private>/);
});
