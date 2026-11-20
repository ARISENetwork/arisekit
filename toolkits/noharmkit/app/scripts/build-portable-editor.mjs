import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = fileURLToPath(new URL("../", import.meta.url));
// tsx supplies the build-time compiler; exported files need no runtime compiler.
const require = createRequire(path.join(appRoot, "node_modules/tsx/package.json"));
const { build } = require("esbuild");
const appRequire = createRequire(path.join(appRoot, "package.json"));
const postcss = appRequire("postcss");
const tailwind = appRequire("@tailwindcss/postcss");
const bundle = await build({
  absWorkingDir: appRoot, entryPoints: ["portable/editor.tsx"], outfile: "portable.js", write: false,
  bundle: true, minify: true, format: "iife", platform: "browser", target: "es2020", jsx: "automatic",
  define: { "process.env.NODE_ENV": '\"production\"' },
  alias: { "next/navigation": path.join(appRoot, "portable/navigation.ts"), "next/link": path.join(appRoot, "portable/link.tsx") },
});
const js = bundle.outputFiles.find((file) => file.path.endsWith(".js")).text;
const moduleCss = bundle.outputFiles.find((file) => file.path.endsWith(".css"))?.text ?? "";
const globals = await readFile(path.join(appRoot, "app/globals.css"), "utf8");
const css = await postcss([tailwind({ base: appRoot, optimize: true })]).process(globals, { from: path.join(appRoot, "app/globals.css") });
const version = (await readFile(path.join(appRoot, "../../../VERSION"), "utf8")).trim();
await writeFile(path.join(appRoot, "portable/editor-shell.json"), JSON.stringify({ js, css: `${css.css}\n${moduleCss}`, version }));
console.log(`Built portable rubric editor (${version}).`);
