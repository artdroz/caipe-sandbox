import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";

const require = createRequire(import.meta.url);
const cli = require.resolve("@docusaurus/core/bin/docusaurus.mjs");

// Production generation must not rewrite the running dev server’s registry.
const result = spawnSync(
  process.execPath,
  [cli, "build", ...process.argv.slice(2)],
  {
    stdio: "inherit",
    env: {
      ...process.env,
      DOCUSAURUS_GENERATED_FILES_DIR_NAME: ".docusaurus-build",
    },
  },
);

if (result.error) throw result.error;
process.exit(result.status ?? 1);
