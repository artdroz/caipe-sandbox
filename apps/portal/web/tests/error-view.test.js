import test from "node:test";
import assert from "node:assert/strict";
import { runtimeError, runtimeStatus, failedCreation, deletionConfirmation } from "../error-view.js";

test("failed creation cancellation explains runtime and disk cleanup", () => {
  const failed = {...sandbox,title:"My micro VM",operation:{kind:"create",state:"needs_attention"}};
  assert.equal(failedCreation(failed), true);
  assert.match(deletionConfirmation(failed), /Cancel creation of My micro VM/);
  assert.match(deletionConfirmation(failed), /runtime resources first/);
  assert.match(deletionConfirmation(failed), /persistent disk/);
  assert.equal(failedCreation({...failed,operation:{kind:"mode",state:"needs_attention"}}), false);
  assert.equal(failedCreation({...failed,operation:{kind:"create",state:"pending"}}), false);
  assert.match(deletionConfirmation({...sandbox,title:"Running VM"}), /^Delete Running VM/);
});

const sandbox = {id:"lush-finch", namespace:"user", uid:"native-id", state:"Error", reason:"SandboxPodCreateFailed", message:'pods "lush-finch" is forbidden:\n' + "long diagnostic ".repeat(500)};

test("runtime errors are collapsed with a copy action and untruncated details", () => {
  const html = runtimeError(sandbox);
  assert.match(html, /<details class="runtime-error" data-error-key="user\/lush-finch\/native-id">/);
  assert.doesNotMatch(html, /<details[^>]*\bopen\b/);
  assert.match(html, /Error details/);
  assert.match(html, /type="button" data-action="copy-error"/);
  assert.match(html, /Copy error/);
  assert.ok(html.includes("long diagnostic ".repeat(500)));
  assert.match(html, /role="status" hidden/);
});

test("runtime errors escape untrusted provider text and identifiers", () => {
  const html = runtimeError({...sandbox,id:'" onclick="bad()',reason:"<script>reason</script>",message:'</pre><img src=x onerror="bad()">'});
  assert.match(html, /&lt;script&gt;reason&lt;\/script&gt;/);
  assert.match(html, /&lt;\/pre&gt;&lt;img/);
  assert.doesNotMatch(html, /<script>|<img|data-id="" onclick=/);
});

test("normal lifecycle states do not render an error box", () => {
  for (const state of ["Running", "Provisioning", "Suspended", "Deleting"]) assert.equal(runtimeError({...sandbox,state}), "");
  assert.match(runtimeError({...sandbox,message:"",reason:""}), /No additional error details are available/);
});

test("failed creation has a readable explanation and copyable technical details", () => {
  const error = "OpenShell needs an administrator to approve the selected runtime.\n\nFAILED_PRECONDITION: runtime approval missing";
  const html = runtimeStatus({...sandbox,state:"Provisioning",operation:{kind:"create",state:"needs_attention",error}});
  assert.match(html, /Creation needs attention/);
  assert.match(html, /class="operation-error-explanation">OpenShell needs an administrator/);
  assert.match(html, /FAILED_PRECONDITION: runtime approval missing/);
  assert.doesNotMatch(html, /awaiting confirmation/);
});

test("a failed action is visible even while its micro VM remains running", () => {
  const html = runtimeStatus({...sandbox,state:"Running",operation:{kind:"mode",state:"needs_attention",error:"Runtime connection lost"}});
  assert.match(html, /runtime-error/);
  assert.match(html, /Runtime connection lost/);
  assert.match(html, /aria-label="Full error message" hidden/);
});
