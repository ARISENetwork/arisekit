import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const source = fileURLToPath(new URL("../../projects/demo/", import.meta.url));
const destination = path.resolve(process.argv[2]);
mkdirSync(destination);

function copyDirectory(from: string, to: string): void {
  for (const entry of readdirSync(from, { withFileTypes: true })) {
    if (from === source && entry.name === "history") continue;
    const input = path.join(from, entry.name);
    const output = path.join(to, entry.name);
    if (entry.isDirectory()) {
      mkdirSync(output);
      copyDirectory(input, output);
    } else if (entry.isFile()) {
      writeFileSync(output, readFileSync(input), { flag: "wx" });
    }
  }
}

copyDirectory(source, destination);
console.log(`Copied the bundled UTI demo into ${destination}`);
