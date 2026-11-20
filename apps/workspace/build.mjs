import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const modules = path.join(root, "toolkits/noharmkit/app/node_modules");
const require = createRequire(path.join(modules, "tsx/package.json"));
const { build } = require("esbuild");
const version = (await readFile(path.join(root, "VERSION"), "utf8")).trim();
const output = path.join(root, "arisekit/workspace_ui");
const assets = path.join(output, "assets");
await mkdir(assets, { recursive: true });
await build({
  absWorkingDir: here,
  entryPoints: ["main.tsx"],
  outfile: path.join(assets, "workspace.js"),
  bundle: true,
  minify: true,
  target: "es2020",
  jsx: "automatic",
  nodePaths: [modules],
  define: {
    __ARISEKIT_VERSION__: JSON.stringify(version),
    "process.env.NODE_ENV": '"production"',
  },
});
await copyFile(path.join(here, "index.html"), path.join(output, "index.html"));
const packages = ["react", "react-dom", "scheduler"];
const licenses = await Promise.all(packages.map(async (name) => {
  const text = await readFile(path.join(modules, name, "LICENSE"), "utf8");
  return name + "\n" + text.trim();
}));
await writeFile(path.join(assets, "LICENSE.txt"), licenses.join("\n\n") + "\n");
