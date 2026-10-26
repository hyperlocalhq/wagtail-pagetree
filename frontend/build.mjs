// Build the wagtail-pagetree admin bundle.
//
// - Entry: src/index.jsx
// - Output: ../src/wagtail_pagetree/static/wagtail_pagetree/js/bundle.js
// - Format: IIFE so it executes on script load.
// - React/ReactDOM are *externalised* and aliased to the globals Wagtail's
//   admin bundle already exposes (window.React / window.ReactDOM). React 16.14.
//
// Pass `--check` to fail (exit 1) if rebuilding produces any diff vs. the
// committed bundle. Used by the pre-commit / CI drift gate.

import { build } from "esbuild";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = resolve(HERE, "..");
const ENTRY = resolve(HERE, "src", "index.jsx");
const OUT = resolve(
  PACKAGE_ROOT,
  "src",
  "wagtail_pagetree",
  "static",
  "wagtail_pagetree",
  "js",
  "bundle.js",
);

// Minimal plugin: rewrite `import X from "react"` → references to
// window.React. Equivalent shim for react-dom. esbuild won't naturally bind
// bare specifiers to a global, so we resolve them to a virtual file we own.
const reactGlobalsPlugin = {
  name: "react-globals",
  setup(b) {
    const VIRT_REACT = "virtual:react";
    const VIRT_REACT_DOM = "virtual:react-dom";

    b.onResolve({ filter: /^react$/ }, () => ({
      path: VIRT_REACT,
      namespace: "react-globals",
    }));
    b.onResolve({ filter: /^react-dom$/ }, () => ({
      path: VIRT_REACT_DOM,
      namespace: "react-globals",
    }));

    b.onLoad({ filter: /.*/, namespace: "react-globals" }, (args) => {
      if (args.path === VIRT_REACT) {
        // Re-export every named React API the bundle imports off the global.
        return {
          contents: `
            const R = window.React;
            export default R;
            export const useState = R.useState;
            export const useEffect = R.useEffect;
            export const useLayoutEffect = R.useLayoutEffect;
            export const useCallback = R.useCallback;
            export const useMemo = R.useMemo;
            export const useRef = R.useRef;
            export const memo = R.memo;
            export const forwardRef = R.forwardRef;
            export const Fragment = R.Fragment;
            export const createElement = R.createElement;
          `,
          loader: "js",
        };
      }
      if (args.path === VIRT_REACT_DOM) {
        return {
          contents: `
            const RD = window.ReactDOM;
            export default RD;
            export const render = RD.render;
            export const unmountComponentAtNode = RD.unmountComponentAtNode;
          `,
          loader: "js",
        };
      }
      return null;
    });
  },
};

async function run() {
  const check = process.argv.includes("--check");

  const result = await build({
    entryPoints: [ENTRY],
    bundle: true,
    format: "iife",
    target: ["es2018"],
    minify: true,
    legalComments: "none",
    sourcemap: false,
    write: false,
    jsx: "transform",
    jsxFactory: "React.createElement",
    jsxFragment: "React.Fragment",
    plugins: [reactGlobalsPlugin],
    logLevel: "info",
    define: {
      "process.env.NODE_ENV": '"production"',
    },
  });

  const next = result.outputFiles[0].contents;

  if (check) {
    if (!existsSync(OUT)) {
      console.error(`drift: committed bundle missing at ${OUT}`);
      process.exit(1);
    }
    const current = await readFile(OUT);
    if (Buffer.compare(current, Buffer.from(next)) !== 0) {
      console.error(
        "drift: committed bundle does not match a fresh rebuild from src/.",
      );
      console.error(`  committed: ${OUT}`);
      console.error("  re-run `npm run build` from frontend/ and commit the result.");
      process.exit(1);
    }
    console.log("ok: bundle matches source.");
    return;
  }

  await mkdir(dirname(OUT), { recursive: true });
  await writeFile(OUT, next);
  console.log(`wrote ${OUT} (${next.length} bytes)`);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
