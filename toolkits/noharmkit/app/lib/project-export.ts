import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { constants } from "node:fs";
import { lstat, readdir, open } from "node:fs/promises";
import { pipeline, Readable } from "node:stream";
import { createGzip } from "node:zlib";
import { casesetDir, inside } from "@/lib/caseset/paths";

export interface ExportEntry { path: string; bytes: number; sha256: string }
export interface ProjectExportManifest {
  format: "arisekit-project-export-v1";
  project: string;
  exportedAt: string;
  fileCount: number;
  totalBytes: number;
  excludedCount: number;
  exclusions: string[];
  directories: string[];
  files: ExportEntry[];
}

export function exportableProjectPath(relative: string): boolean {
  return relative.length > 0 && !relative.includes("\\") && !/holdout/i.test(relative) && relative.split("/").every(part =>
    part !== ".." && part !== "." && part !== "" && !part.startsWith(".") && !/^(node_modules|venv|__pycache__|tmp|temp|cache|credentials?|secrets?)$/i.test(part)
    && !/(^|[-_.])(credentials?|secrets?|tokens?|api[-_]?keys?|private[-_]?keys?)([-_.]|$)/i.test(part)
    && !/\.(tmp|temp|bak|swp|pyc|pem|key|p12|pfx|crt|log)$/i.test(part));
}

export async function projectExportInventory(root: string, project: string): Promise<{ folder: string; manifest: ProjectExportManifest }> {
  const folder = casesetDir(root, project);
  if (/holdout/i.test(folder)) throw new TypeError("This project path is excluded from export.");
  const files: ExportEntry[] = [];
  const directories: string[] = [];
  let excludedCount = 0;
  const walk = async (relative: string): Promise<void> => {
    for (const entry of (await readdir(relative ? inside(folder, relative) : folder, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      const name = relative ? `${relative}/${entry.name}` : entry.name;
      if (!exportableProjectPath(name) || entry.isSymbolicLink()) { excludedCount += 1; continue; }
      const target = inside(folder, name);
      if (entry.isDirectory()) { directories.push(name); await walk(name); }
      else if (entry.isFile()) {
        const hash = createHash("sha256");
        let bytes = 0;
        for await (const chunk of createReadStream(target)) { hash.update(chunk); bytes += chunk.length; }
        files.push({ path: name, bytes, sha256: hash.digest("hex") });
      }
    }
  };
  await walk("");
  return { folder, manifest: { format: "arisekit-project-export-v1", project, exportedAt: new Date().toISOString(), fileCount: files.length, totalBytes: files.reduce((total, file) => total + file.bytes, 0), excludedCount, exclusions: ["Paths containing holdout", "Hidden files and directories", "Credentials, secrets, private keys, and token files", "Temporary files, caches, dependencies, logs, and symbolic links"], directories, files } };
}

function tarHeader(name: string, size: number, type = "0"): Buffer {
  const header = Buffer.alloc(512);
  header.write(name, 0, 100, "utf8");
  const octal = (value: number, start: number, length: number): void => { header.write(`${value.toString(8).padStart(length - 1, "0")}\0`, start, length, "ascii"); };
  octal(type === "5" ? 0o700 : 0o600, 100, 8); octal(0, 108, 8); octal(0, 116, 8); octal(size, 124, 12); octal(0, 136, 12);
  header.fill(32, 148, 156);
  header.write(type, 156, 1, "ascii"); header.write("ustar\0", 257, 6, "ascii"); header.write("00", 263, 2, "ascii");
  const checksum = header.reduce((sum, byte) => sum + byte, 0);
  header.write(`${checksum.toString(8).padStart(6, "0")}\0 `, 148, 8, "ascii");
  return header;
}

function* tarEntryHeader(name: string, size: number, type = "0"): Generator<Buffer> {
  if (Buffer.byteLength(name) > 100) {
    const long = Buffer.from(`${name}\0`);
    yield tarHeader("././@LongLink", long.length, "L"); yield long;
    if (long.length % 512) yield Buffer.alloc(512 - long.length % 512);
  }
  yield tarHeader(name, size, type);
}

export function projectArchiveStream(folder: string, manifest: ProjectExportManifest): ReadableStream<Uint8Array> {
  async function* archive(): AsyncGenerator<Buffer> {
    const inventory = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`);
    yield* tarEntryHeader("ARISEKIT-EXPORT.json", inventory.length); yield inventory;
    if (inventory.length % 512) yield Buffer.alloc(512 - inventory.length % 512);
    yield tarHeader("project/", 0, "5");
    for (const directory of manifest.directories) {
      yield* tarEntryHeader(`project/${directory}/`, 0, "5");
    }
    for (const entry of manifest.files) {
      const target = inside(folder, entry.path);
      if ((await lstat(target)).isSymbolicLink()) throw new Error("A project file changed during export. Retry the download.");
      const handle = await open(target, constants.O_RDONLY | constants.O_NOFOLLOW);
      try {
        const current = await handle.stat();
        if (!current.isFile() || current.size !== entry.bytes) throw new Error("A project file changed during export. Retry the download.");
        yield* tarEntryHeader(`project/${entry.path}`, entry.bytes);
        const hash = createHash("sha256");
        for await (const chunk of handle.createReadStream({ autoClose: false })) { hash.update(chunk); yield chunk; }
        if (hash.digest("hex") !== entry.sha256) throw new Error("A project file changed during export. Retry the download.");
      } finally { await handle.close(); }
      if (entry.bytes % 512) yield Buffer.alloc(512 - entry.bytes % 512);
    }
    yield Buffer.alloc(1024);
  }
  const compressed = createGzip();
  pipeline(Readable.from(archive()), compressed, () => {});
  return Readable.toWeb(compressed) as ReadableStream<Uint8Array>;
}
