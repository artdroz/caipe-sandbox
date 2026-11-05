import test from "node:test";
import assert from "node:assert/strict";
import { dateTime, sandboxMetadata } from "../timestamps.js";

test("unknown or invalid timestamps remain unknown without rendering input", () => {
  for (const value of [undefined, null, "", 0, "not a date", '<script>alert(1)</script>']) {
    assert.equal(dateTime(value), "—");
  }
});

test("localized timestamps retain exact ISO values and full-date tooltips", () => {
  const first = "2025-01-02T03:04:05+00:00", last = "2026-11-04T14:05:06+00:00";
  const markup = sandboxMetadata({created_at:first, updated_at:last, namespace:"team-engineering", profile:{id:"engineering",title:"Engineering"}});
  assert.match(markup, /Created/);
  assert.match(markup, /team-engineering/);
  assert.doesNotMatch(markup, /Engineering|Profile/);
  assert.doesNotMatch(markup, /Updated/);
  assert.match(markup, /datetime="2025-01-02T03:04:05.000Z"/);
  assert.doesNotMatch(markup, /datetime="2026-11-04T14:05:06.000Z"/);
  assert.match(dateTime(first, true), /title="[^"]*2025[^"]*"/);
  assert.match(dateTime(last), /2026/);
});

test("card metadata handles absent values and escapes namespace and owner text", () => {
  assert.doesNotMatch(sandboxMetadata({}), /Profile/);
  const markup = sandboxMetadata({namespace:'<img src=x>',owner:'<script>bad</script>'});
  assert.doesNotMatch(markup, /<img|<script/);
  assert.match(markup, /&lt;img src=x&gt;/);
  assert.match(markup, /&lt;script&gt;bad&lt;\/script&gt;/);
});
