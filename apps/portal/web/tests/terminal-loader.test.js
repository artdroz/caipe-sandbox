import test from "node:test";
import assert from "node:assert/strict";
import { terminalLoader } from "../terminal-loader.js";

test("concurrent terminal opens share a download and reuse the loaded runtime", async () => {
  let downloads = 0, complete;
  const runtime = {Terminal: class {}};
  const load = terminalLoader(() => {
    downloads++;
    return new Promise(resolve => { complete = resolve; });
  });
  const first = load(), second = load();
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(downloads, 1);
  complete(runtime);
  assert.equal(await first, runtime);
  assert.equal(await load(), runtime);
  assert.equal(downloads, 1);
});

test("a failed module download allows a new request URL on retry", async () => {
  const attempts = [];
  const load = terminalLoader(attempt => {
    attempts.push(attempt);
    if (!attempt) throw new Error("offline");
    return {Terminal: class {}};
  });
  const first = load();
  assert.equal(load(), first);
  await assert.rejects(first, /offline/);
  await load();
  await load();
  assert.deepEqual(attempts, [0, 1]);
});
