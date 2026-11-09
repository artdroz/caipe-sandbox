import { readFile, writeFile } from "node:fs/promises";
import { build } from "esbuild";
await build({entryPoints: {portal: "web/main.js", "terminal-runtime": "web/terminal-runtime.js"},
  outdir: "portal/static", bundle: true, external: ["./terminal-runtime.js"],
  format: "esm", minify: true, target: "es2022", legalComments: "inline"});

await writeFile("portal/static/licenses.txt", (await Promise.all(["@xterm/xterm", "@xterm/addon-fit", "@xterm/addon-search", "diff"].map(async (name) => name + "\n" + await readFile("node_modules/" + name + "/LICENSE", "utf8")))).join("\n\n"));
