import { mkdir } from "node:fs/promises";
import { build } from "esbuild";

await mkdir("services/render-worker/dist", { recursive: true });

await Promise.all([
  build({
    entryPoints: ["services/render-worker/src/page-entry.ts"],
    outfile: "services/render-worker/dist/page-entry.js",
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    sourcemap: false,
  }),
  build({
    entryPoints: ["services/render-worker/src/spike.ts"],
    outfile: "services/render-worker/dist/spike.js",
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    packages: "external",
    sourcemap: false,
  }),
]);
