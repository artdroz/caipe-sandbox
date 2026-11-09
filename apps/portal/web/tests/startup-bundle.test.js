import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";

test("inventory loads without terminal JavaScript; the terminal remains a separate relative import", async () => {
  const result = await build({
    entryPoints: {portal: "web/main.js", "terminal-runtime": "web/terminal-runtime.js"},
    outdir: "portal/static", bundle: true, external: ["./terminal-runtime.js"],
    format: "esm", minify: true, target: "es2022", write: false, metafile: true,
  });
  const inventory = result.metafile.outputs["portal/static/portal.js"];
  const terminal = result.metafile.outputs["portal/static/terminal-runtime.js"];
  assert.ok(!Object.keys(inventory.inputs).some(path => path.includes("node_modules/@xterm/") && !path.endsWith(".css")));
  assert.ok(Object.keys(terminal.inputs).some(path => path.includes("node_modules/@xterm/xterm/")));
  const script = result.outputFiles.find(file => file.path.endsWith("/portal.js")).text;
  assert.match(script, /"\.\/terminal-runtime\.js"/);
  assert.ok(script.includes("import("));
  assert.ok(inventory.bytes < terminal.bytes, "terminal code must stay out of the initial bundle");
});
