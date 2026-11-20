interface CaseSourcePanelProps {
  presentation: string;
  recommendations: string;
  response?: { label: string; text: string };
  compact?: boolean;
  children?: React.ReactNode;
}

export default function CaseSourcePanel({ presentation, recommendations, response, compact = false, children }: CaseSourcePanelProps) {
  const heading = compact ? "mb-1.5 text-[13px] font-bold text-[hsl(var(--primary))]" : "mb-3 text-lg font-semibold text-[hsl(var(--foreground))]";
  const body = compact ? "whitespace-pre-wrap text-[13px] leading-[1.55] text-[hsl(var(--foreground))]" : "whitespace-pre-wrap text-sm leading-relaxed text-[hsl(var(--foreground))]";
  const gap = compact ? "mb-4 border-b border-[hsl(var(--border))] pb-4" : "mb-7";
  return (
    <aside className={`rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--card))] ${compact ? "p-4 xl:top-20 xl:max-h-[calc(100vh-6rem)]" : "p-6 xl:top-24 xl:max-h-[calc(100vh-8rem)]"} xl:sticky xl:overflow-y-auto`}>
      <section className={gap}>
        <h2 className={heading}>Task</h2>
        <p className={body}>{presentation}</p>
      </section>
      <section className={response || children ? gap : undefined}>
        <h2 className={heading}>Solution</h2>
        <p className={body}>{recommendations}</p>
      </section>
      {response && (
        <section className={children ? gap : undefined}>
          <h2 className={heading}>{response.label}</h2>
          <p className={body}>{response.text}</p>
        </section>
      )}
      {children}
    </aside>
  );
}
