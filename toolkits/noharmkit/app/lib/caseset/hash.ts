import { createHash } from "node:crypto";

// Byte-identical to Python's json.dumps(value, sort_keys=True): ", " and ": " separators, sorted keys,
// and every code unit outside printable ASCII escaped as \uXXXX (ensure_ascii). arisekit/common/hashing.py
// json_sha256 hashes that string; judge records carry it as rubric_sha256, scored records as judgment_sha256.
// Parity holds on the value domain answer tables and judge outputs use: objects, arrays, strings, booleans,
// null, and safe integers. Anything else throws rather than hash differently from Python. (A float written
// as 8.0 parses to 8 here and would read as changed; the pipeline writes these files with integers.)
export function pythonJsonDumps(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error(`cannot hash ${value} like Python: only safe integers are supported`);
    return String(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value).replace(/[\u007f-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
  }
  if (Array.isArray(value)) return `[${value.map(pythonJsonDumps).join(", ")}]`;
  if (typeof value !== "object") throw new Error(`cannot hash a ${typeof value} like Python`);
  const object = value as Record<string, unknown>;
  const keys = Object.keys(object);
  // JavaScript sorts UTF-16 code units and Python sorts code points; they can disagree only on keys with surrogates.
  if (keys.some((k) => /[\ud800-\udfff]/.test(k))) throw new Error("cannot hash an object key outside the Basic Multilingual Plane like Python");
  return `{${keys.sort().map((k) => `${pythonJsonDumps(k)}: ${pythonJsonDumps(object[k])}`).join(", ")}}`;
}

export function tableSha256(table: unknown): string {
  return createHash("sha256").update(pythonJsonDumps(table), "utf8").digest("hex");
}

// pipeline/e2e/judge.py text_sha256 hashes the source text's exact UTF-8 bytes.
export function textSha256(text: string): string {
  return createHash("sha256").update(text, "utf8").digest("hex");
}
