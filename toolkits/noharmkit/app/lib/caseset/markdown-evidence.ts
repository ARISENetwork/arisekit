import { highlight } from "@/lib/caseset/lens";
import type { EvidenceSpan } from "@/lib/caseset/lens";

interface Node {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  position?: { start: { offset?: number }; end: { offset?: number } };
  children?: Node[];
}

// Preserve source offsets when Markdown decodes escapes and character references.
function offsets(raw: string, value: string, start: number): Array<[number, number]> | null {
  const exact = raw.indexOf(value);
  if (exact >= 0) return Array.from({ length: value.length }, (_, i) => [start + exact + i, start + exact + i + 1]);
  const result: Array<[number, number]> = [];
  let at = 0;
  for (let i = 0; i < value.length; i += 1) {
    const begin = at;
    const entity = /^&(?:#[0-9]+|#x[0-9a-f]+|[a-z][a-z0-9]+);/i.exec(raw.slice(at));
    if (entity && !value.slice(i).startsWith(entity[0])) {
      at += entity[0].length;
      result.push([start + begin, start + at]);
      if (value.codePointAt(i)! > 0xffff) { result.push([start + begin, start + at]); i += 1; }
      continue;
    }
    if (raw[at] === "\\" && /[!"#$%&'()*+,\-./:;<=>?@[\]\\^_`{|}~]/.test(raw[at + 1] ?? "")) at += 1;
    if (raw[at] === "\r" && value[i] === "\n") at += 1;
    if (raw[at] !== value[i]) return null;
    at += 1;
    result.push([start + begin, start + at]);
  }
  return at === raw.length ? result : null;
}

// Mark rendered text nodes, leaving headings, emphasis, lists, and links intact.
export function markdownEvidence(source: string, spans: EvidenceSpan[]) {
  let offset = 0;
  const ranges = highlight(source, spans).segments.map((segment) => {
    const start = offset;
    offset += segment.text.length;
    return { start, end: offset, keys: segment.keys };
  }).filter((range) => range.keys.length);
  const labels = new Map(spans.map((span) => [span.key, span.label]));
  return () => (tree: Node): void => {
    const visit = (node: Node): void => {
      if (!node.children) return;
      node.children = node.children.flatMap((child) => {
        const start = child.position?.start.offset;
        const end = child.position?.end.offset;
        if (child.type !== "text" || !child.value || start === undefined || end === undefined) {
          visit(child);
          return [child];
        }
        const positions = offsets(source.slice(start, end), child.value, start);
        if (!positions) return [child];
        const runs: Array<{ value: string; keys: string[] }> = [];
        for (let i = 0; i < child.value.length; i += 1) {
          const [from, to] = positions[i];
          const keys = [...new Set(ranges.filter((range) => range.start <= from && range.end >= to).flatMap((range) => range.keys))];
          const last = runs.at(-1);
          if (last && last.keys.join(" ") === keys.join(" ")) last.value += child.value[i];
          else runs.push({ value: child.value[i], keys });
        }
        return runs.map((run): Node => run.keys.length ? {
          type: "element", tagName: "mark",
          properties: {
            title: run.keys.map((key) => labels.get(key) ?? key).join("\n"),
            "data-evidence-keys": JSON.stringify(run.keys),
            "data-evidence-kind": run.keys.some((key) => key.startsWith("off:") || key.includes(":u")) ? "unmapped" : "mapped",
          },
          children: [{ type: "text", value: run.value }],
        } : { type: "text", value: run.value });
      });
    };
    visit(tree);
  };
}
