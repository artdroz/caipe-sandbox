import test from "node:test";
import assert from "node:assert/strict";
import { highlightJson, jsonBlock } from "../json-view.js";

function plainText(markup) {
  return markup.replace(/<\/?span\b[^>]*>/g, "").replace(/&(amp|lt|gt|quot|#39);/g, (entity) => ({"&amp;":"&","&lt;":"<","&gt;":">","&quot;":'"',"&#39;":"'"}[entity]));
}

test("JSON highlighting distinguishes keys, values, numbers, literals and punctuation", () => {
  const value = {image:"example:latest", count:-2.5, exponent:1e30, enabled:true, disabled:false, policy:null, nested:[0, {}]};
  const markup = highlightJson(value);
  for (const type of ["key", "string", "number", "boolean", "null", "punctuation"]) assert.match(markup, new RegExp(`class="json-${type}"`));
  assert.equal(plainText(markup), JSON.stringify(value, null, 2));
});

test("profile scripts and strings remain escaped text with exact JSON formatting", () => {
  const value = {'a"key': '</code><script>alert("x")</script> & \'quoted\'\ntrue false null 12', command:'echo "value": 1\\path'};
  const markup = highlightJson(value);
  assert.doesNotMatch(markup, /<script|<\/code>|onerror=/);
  assert.equal(plainText(markup), JSON.stringify(value, null, 2));
  assert.equal((markup.match(/class="json-string"/g) || []).length, 2);
});

test("primitive and empty JSON values retain their exact content", () => {
  for (const value of [null, true, false, 0, -3, "", [], {}, "&amp; &#39;"]) assert.equal(plainText(highlightJson(value)), JSON.stringify(value, null, 2));
});

test("JSON blocks provide a copy action and a keyboard-focusable code region", () => {
  const markup = jsonBlock({enabled:true});
  assert.match(markup, /data-copy-json>Copy JSON<\/button>/);
  assert.match(markup, /<pre class="json-code" tabindex="0" aria-label="JSON configuration"><code>/);
});
