// esbuild.config.mjs — Produktions-Bundles für die React-Pages.
//
// Baut Bundles:
//   1. op-workflow.bundle.js  → ../hausverwaltung/public/op_workflow/
//   2. mk-workflow.bundle.js  → ../hausverwaltung/public/mieterkonto_workflow/
//   3. mahn-workflow.bundle.js → ../hausverwaltung/public/mahnung_workflow/
//
// Run:
//   npm install
//   npm run build         # einmaliger Build (beide Bundles)
//   npm run watch         # Dev: re-baut bei Änderungen

import { build, context } from "esbuild";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.resolve(__dirname, "../hausverwaltung/public");
const isProd = process.env.NODE_ENV === "production";

const COMMON = {
  bundle: true,
  format: "iife",
  jsx: "transform",
  jsxFactory: "React.createElement",
  jsxFragment: "React.Fragment",
  loader: { ".jsx": "jsx" },
  target: ["es2020"],
  minify: isProd,
  sourcemap: !isProd,
  define: { "process.env.NODE_ENV": JSON.stringify(process.env.NODE_ENV || "development") },
  inject: [path.resolve(__dirname, "react-shim.js")],
  external: [],
};

const targets = [
  {
    name: "op-workflow",
    src: path.join(PUBLIC, "op_workflow"),
    out: "op-workflow.bundle.js",
    entries: ["tweaks-panel.jsx", "op-components.jsx", "op-actions.jsx", "op-app.jsx"],
    globalName: "OpWorkflow",
  },
  {
    name: "mk-workflow",
    src: path.join(PUBLIC, "mieterkonto_workflow"),
    out: "mk-workflow.bundle.js",
    entries: [
      "tweaks-panel.jsx",
      "mk-components.jsx",
      "mk-variant-a.jsx",
      "mk-variant-b.jsx",
      "mk-variant-c.jsx",
      "mk-app.jsx",
    ],
    globalName: "MkWorkflow",
  },
  {
    name: "mahn-workflow",
    src: path.join(PUBLIC, "mahnung_workflow"),
    out: "mahn-workflow.bundle.js",
    entries: ["tweaks-panel.jsx", "mahn-components.jsx", "mahn-letter.jsx", "mahn-app.jsx"],
    globalName: "MahnWorkflow",
  },
];

function makeConfig(target) {
  const outfile = path.join(target.src, target.out);
  return {
    ...COMMON,
    stdin: {
      contents: target.entries.map((f) => `import "./${f}";`).join("\n"),
      resolveDir: target.src,
      sourcefile: `${target.name}-entry.jsx`,
      loader: "jsx",
    },
    outfile,
    globalName: target.globalName,
    banner: { js: `/* ${target.name} bundle — siehe op_workflow_build/esbuild.config.mjs */` },
  };
}

const watching = process.argv.includes("--watch");

if (watching) {
  for (const target of targets) {
    const ctx = await context(makeConfig(target));
    await ctx.watch();
    console.log("watching", target.name, "@", target.src);
  }
} else {
  for (const target of targets) {
    await build(makeConfig(target));
    console.log("built", target.name, "→", path.join(target.src, target.out));
  }
}
