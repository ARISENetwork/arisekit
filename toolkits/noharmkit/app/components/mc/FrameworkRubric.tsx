import { Card } from "@/components/mc/ui";

const SOURCE_LINK = "text-xs text-mc-accent underline underline-offset-4 transition-colors hover:text-mc-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-mc-accent motion-reduce:transition-none";

export default function FrameworkRubric() {
  return <Card className="mt-4 p-5 sm:p-6">
    <h2 className="m-0 text-[15px] font-semibold">Clinical rubrics and measurement</h2>
    <p className="mb-5 mt-2 leading-relaxed">Rubrics make clinical judgments explicit: what counts as appropriate care, which errors matter, and how severe their potential consequences are.</p>
    <div className="grid gap-6 md:grid-cols-2">
      <section>
        <h3 className="m-0 text-sm font-semibold">Clinical appropriateness</h3>
        <p className="mb-3 mt-2 text-sm leading-relaxed text-mc-muted">Judge whether an action's expected benefits outweigh its risks for this patient, using clinical evidence and expert judgment.</p>
        <ol aria-label="Appropriateness categories" className="m-0 mb-3 flex list-none flex-wrap gap-2 p-0 text-xs">
          {[
            ["Inappropriate", "bg-mc-bad-bg text-mc-bad"],
            ["Uncertain", "bg-mc-llm-bg text-mc-llm"],
            ["Appropriate", "bg-mc-human-bg text-mc-human"],
          ].map(([label, tone]) => <li className={`rounded-md px-2.5 py-2 ${tone}`} key={label}>{label}</li>)}
        </ol>
        <a className={SOURCE_LINK} href="https://www.rand.org/content/dam/rand/pubs/monograph_reports/2011/MR1269.pdf" target="_blank" rel="noopener noreferrer" aria-label="RAND/UCLA Appropriateness Method (opens in a new tab)">RAND/UCLA Appropriateness Method</a>
      </section>
      <section>
        <h3 className="m-0 text-sm font-semibold">Potential harm</h3>
        <p className="mb-3 mt-2 text-sm leading-relaxed text-mc-muted">Use explicit severity definitions to rate potential harm from incorrect actions and missed necessary care.</p>
        <ol aria-label="Harm categories adapted from the WHO patient safety framework" className="m-0 mb-3 flex list-none flex-wrap gap-2 p-0 text-xs">
          {[
            ["None", "bg-mc-human-bg text-mc-human"],
            ["Mild", "bg-mc-llm-bg text-mc-llm"],
            ["Moderate", "bg-mc-llm-bg text-mc-llm"],
            ["Severe", "bg-mc-bad-bg text-mc-bad"],
            ["Death", "bg-mc-bad-bg text-mc-bad"],
          ].map(([label, tone]) => <li className={`rounded-md px-2.5 py-2 ${tone}`} key={label}>{label}</li>)}
        </ol>
        <div className="flex flex-col items-start gap-2">
          <a className={SOURCE_LINK} href="https://www.who.int/publications-detail-redirect/WHO-IER-PSP-2010.2" target="_blank" rel="noopener noreferrer" aria-label="World Health Organization patient safety framework (opens in a new tab)">World Health Organization patient safety framework</a>
          <p className="m-0 text-xs text-mc-muted">Alternative: <a className={SOURCE_LINK} href="https://www.ahrq.gov/sites/default/files/wysiwyg/npsd/data/npsd-chartbook-2022.pdf#page=27" target="_blank" rel="noopener noreferrer" aria-label="Agency for Healthcare Research and Quality (AHRQ) Common Formats harm scale (opens in a new tab)">AHRQ Common Formats harm scale</a></p>
        </div>
      </section>
    </div>
    <p className="mb-0 mt-5 bg-mc-surface-2 p-3 text-sm leading-relaxed text-mc-muted">NOHARM is agnostic to the framework or taxonomy. Choose an established, validated clinical framework or taxonomy suited to your setting rather than inventing one.</p>
    <section className="mt-5 border-t border-mc-line pt-4">
      <h3 className="m-0 text-sm font-semibold">Interpretable results</h3>
      <p className="mb-3 mt-2 text-sm leading-relaxed text-mc-muted">Report clinical appropriateness and the frequency of each harm severity, with the denominator and rating method.</p>
      <p className="m-0 bg-mc-accent-bg p-3 text-sm leading-relaxed"><strong className="font-semibold">Illustrative result:</strong> 10% of evaluated responses contained an error that could cause severe harm.</p>
    </section>
  </Card>;
}
