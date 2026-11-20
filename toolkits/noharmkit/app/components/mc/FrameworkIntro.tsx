import { useId } from "react";
import { FRAMEWORK } from "@/components/mc/framework-copy";

export default function FrameworkIntro() {
  const copy = FRAMEWORK;
  const applicationsId = useId();
  const lead = <p className="m-0"><strong className="font-medium"><a className="rounded-sm text-mc-accent underline underline-offset-4 transition-colors hover:text-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent motion-reduce:transition-none" href={FRAMEWORK.preprint} target="_blank" rel="noopener noreferrer" aria-label="NOHARM preprint (opens in a new tab)">NOHARM</a>{" "}{copy.lead.statement}</strong>{" "}{copy.lead.explanation}</p>;
  return <div className="text-base leading-relaxed text-mc-ink">
    {lead}
    <section aria-label="Clinical performance" className="my-5 flex flex-col gap-3 bg-mc-accent-bg p-5">
      <p className="m-0 text-xl font-semibold leading-snug tracking-tight">{copy.closing.statement}</p>
      <p className="m-0">{copy.context.statement}{" "}{copy.context.analogy}</p>
      <p className="m-0">{copy.closing.explanation}</p>
    </section>
    <section aria-labelledby={applicationsId}>
      <h2 className="m-0 mb-2 text-sm font-semibold" id={applicationsId}>Applications</h2>
      <p className="m-0">{copy.context.scope}</p>
    </section>
  </div>;
}
