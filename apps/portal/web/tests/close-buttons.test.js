import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../../portal/static/index.html", import.meta.url), "utf8");
const buttons = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)];

test("close controls use an icon with an accessible name and never submit forms", () => {
  const closeButtons = buttons.filter(([,attributes]) => /class="[^"]*\bclose-button\b/.test(attributes));
  assert.equal(closeButtons.length, 13);
  for (const [,attributes,content] of closeButtons) {
    assert.match(attributes, /type="button"/);
    assert.match(attributes, /aria-label="Close [^"]+"/);
    assert.match(content, /data-icon="close"/);
    assert.equal(content.replace(/<[^>]*>/g, "").trim(), "");
  }
});

test("all standard dialogs have a header close action", () => {
  for (const target of ["resource-dialog", "sharing-dialog", "power-dialog", "admin-sandbox-dialog", "admin-user-dialog"]) {
    assert.ok(buttons.some(([,attributes]) => attributes.includes(`data-close-dialog="${target}"`)), target);
  }
  for (const id of ["cancel-create", "close-configuration", "close-message", "cancel-admin-controls", "close-terminal", "close-terminal-search"]) {
    assert.ok(buttons.some(([,attributes]) => attributes.includes(`id="${id}"`) && attributes.includes("close-button")), id);
  }
});
