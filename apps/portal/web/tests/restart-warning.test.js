import test from "node:test";
import assert from "node:assert/strict";
import {restartWarning} from "../restart-warning.js";

test("restart warnings expose the countdown to hover, keyboard and screen-reader users", () => {
  const html = restartWarning("Portal restarting in 2m 05s. Save your work.", "shell");
  assert.match(html, /tabindex="0" role="img"/);
  assert.match(html, /aria-label="Portal restarting in 2m 05s/);
  assert.match(html, /class="field-tooltip"/);
  assert.match(html, /<span>Shell will restart<\/span>/);
  assert.equal(restartWarning(null), "");
});

test("restart warnings escape provider messages and session identifiers", () => {
  const html = restartWarning('<img src=x onerror="bad()">', '" onfocus="bad()');
  assert.doesNotMatch(html, /<img|data-restart-key="" onfocus=/);
  assert.match(html, /&lt;img/);
  assert.match(html, /&quot; onfocus=/);
});
