import { useId } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { markdownEvidence } from "@/lib/caseset/markdown-evidence";
import type { EvidenceSpan } from "@/lib/caseset/lens";
import { EvidenceMark } from "@/components/mc/EvidenceLinker";

const COMPONENTS: Components = {
  h1: ({ node: _node, className, ...props }) => <h3 {...props} className={`m-0 text-xl font-semibold leading-tight ${className ?? ""}`} />,
  h2: ({ node: _node, className, ...props }) => <h4 {...props} className={`m-0 text-lg font-semibold leading-tight ${className ?? ""}`} />,
  h3: ({ node: _node, className, ...props }) => <h5 {...props} className={`m-0 text-base font-semibold ${className ?? ""}`} />,
  h4: ({ node: _node, className, ...props }) => <h6 {...props} className={`m-0 text-sm font-semibold ${className ?? ""}`} />,
  h5: ({ node: _node, className, ...props }) => <h6 {...props} className={`m-0 text-sm font-semibold ${className ?? ""}`} />,
  h6: ({ node: _node, className, ...props }) => <h6 {...props} className={`m-0 text-sm font-semibold ${className ?? ""}`} />,
  p: ({ children }) => <p className="m-0 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="m-0 list-disc space-y-1 pl-5">{children}</ul>,
  ol: ({ children, start }) => <ol className="m-0 list-decimal space-y-1 pl-5" start={start}>{children}</ol>,
  li: ({ node: _node, className, ...props }) => <li {...props} className={`leading-relaxed [&>ul]:mt-1 [&>ol]:mt-1 ${className?.includes("task-list-item") ? "list-none" : ""}`} />,
  a: ({ node: _node, ...props }) => <a {...props} className="break-words text-mc-accent underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent" />,
  blockquote: ({ children }) => <blockquote className="m-0 space-y-2 rounded-md border border-mc-line bg-mc-surface-2 p-3">{children}</blockquote>,
  pre: ({ children }) => <pre className="m-0 overflow-x-auto rounded-md border border-mc-line bg-mc-surface-2 p-3 font-mc-mono text-xs [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0">{children}</pre>,
  code: ({ children, className }) => <code className={`rounded-sm border border-mc-line bg-mc-surface-2 px-1 py-0.5 font-mc-mono text-[0.9em] ${className ?? ""}`}>{children}</code>,
  table: ({ children }) => <div aria-label="Markdown table" className="overflow-x-auto rounded-md border border-mc-line focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent" role="region" tabIndex={0}><table className="w-full border-collapse text-sm">{children}</table></div>,
  thead: ({ children }) => <thead className="bg-mc-surface-2">{children}</thead>,
  th: ({ children, style }) => <th className="border-b border-mc-line px-3 py-2 text-left font-semibold" scope="col" style={style}>{children}</th>,
  td: ({ children, style }) => <td className="border-t border-mc-line px-3 py-2 align-top" style={style}>{children}</td>,
  hr: () => <hr className="m-0 border-0 border-t border-mc-line" />,
  img: ({ src, alt, title }) => <img alt={alt ?? ""} className="h-auto max-w-full rounded-md" src={src} title={title} />,
  mark: ({ node, ...props }) => <EvidenceMark {...props} spanKeys={JSON.parse(String(node?.properties["data-evidence-keys"] ?? "[]"))} kind={String(node?.properties["data-evidence-kind"] ?? "mapped")} />,
};

const INLINE_ELEMENTS = ["p", "a", "em", "strong", "del", "code", "br", "mark"];
const INLINE_COMPONENTS: Components = { ...COMPONENTS, p: ({ children }) => <span>{children}</span> };

interface MarkdownNode {
  type: string;
  children?: MarkdownNode[];
  properties?: Record<string, unknown>;
}

// The parser namespaces note links but uses one fixed accessibility-label ID.
function footnoteLabels(prefix: string) {
  return () => (tree: MarkdownNode): void => {
    const visit = (node: MarkdownNode): void => {
      const props = node.properties;
      if (props?.id === "footnote-label") props.id = `${prefix}footnote-label`;
      if (Array.isArray(props?.ariaDescribedBy)) {
        props.ariaDescribedBy = props.ariaDescribedBy.map((id) => id === "footnote-label" ? `${prefix}footnote-label` : id);
      }
      node.children?.forEach(visit);
    };
    visit(tree);
  };
}

export default function PipelineMarkdown({ children, inline = false, evidenceSpans = [] }: { children: string; inline?: boolean; evidenceSpans?: EvidenceSpan[] }) {
  const prefix = `md-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}-`;
  const content = <Markdown allowedElements={inline ? INLINE_ELEMENTS : undefined} components={inline ? INLINE_COMPONENTS : COMPONENTS} remarkPlugins={[remarkGfm]} remarkRehypeOptions={{ clobberPrefix: prefix }} rehypePlugins={[footnoteLabels(prefix), ...(evidenceSpans.length ? [markdownEvidence(children, evidenceSpans)] : [])]} unwrapDisallowed={inline}>{children}</Markdown>;
  return inline ? <span>{content}</span> : <div className="min-w-0 space-y-3 break-words leading-relaxed">{content}</div>;
}
