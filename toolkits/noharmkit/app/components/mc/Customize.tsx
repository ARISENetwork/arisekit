import PromptBox from "@/components/mc/PromptBox";
import { Card } from "@/components/mc/ui";

const DECISIONS = [
  {
    name: "RAND review",
    options: [
      ["Quick", "One independent rating round for an initial review."],
      ["Full", "Two rating rounds with discussion and a moderator. Requires more model calls."],
    ],
  },
  {
    name: "RAND panel size",
    options: [
      ["Three members", "The minimum supported panel, with fewer model calls."],
      ["Larger panel", "Include more model raters, at a higher cost per review."],
    ],
  },
  {
    name: "RAND panel models",
    options: [
      ["Different model families", "Compare ratings across models with different training and behavior."],
      ["Repeated model", "Check a model's consistency across independent calls, rather than diversity across models."],
    ],
  },
  {
    name: "Models to benchmark",
    options: [
      ["Focused comparison", "Test a small set of models relevant to your intended use."],
      ["Broader comparison", "Include a range of model families and capabilities to explore differences in performance."],
    ],
  },
  {
    name: "Severity weights",
    options: [
      ["Toolkit weights", "Uncertain 1, mild 3, moderate 24, severe 72. More severe harms contribute more to the score."],
      ["Custom weights", "Use a different increasing scale for a separate comparison. Requires a scoring-code change and new results."],
    ],
  },
  {
    name: "Responses per item",
    options: [
      ["One response per model", "A smaller run, with one response for each item and model."],
      ["Repeated responses", "Measure variation across multiple model responses. Choose the count before collecting responses."],
    ],
  },
  {
    name: "Autograder",
    options: [
      ["One fixed judge", "Use the same model and reasoning setting to map all model responses onto the rubric."],
      ["Compare judges", "Grade the same model responses in separate runs to examine how the judge affects results."],
    ],
  },
  {
    name: "Clinical review",
    options: [
      ["Automated drafts", "Explore the pipeline with provisional rubrics and results."],
      ["Clinician review", "Review the rubric and grading evidence against your declared clinical review requirements."],
    ],
  },
] as const;

export default function Customize({ benchmark, projectsRoot, textV2 = false }: { benchmark?: string; projectsRoot?: string; textV2?: boolean }) {
  const target = benchmark ? `the ${benchmark} project` : "a new benchmark project";
  const location = projectsRoot ? ` in ${projectsRoot}` : "";
  const prompt = `Help me choose the benchmark design for ${target}${location}. Inspect existing project configuration and results first. Walk through RAND review mode, panel size and panel models, candidate models, ${textV2 ? "the project-pinned judge and scoring contracts" : "severity weights"}, response trials, autograder model and reasoning, and clinical review requirements. Explain the alternatives and cost tradeoffs. Identify which choices are already set and which need a code change or a fresh project/run. Preserve existing evidence. Agree on the plan, provider routes, and spend before changing settings or running models.`;
  return (
    <Card className="mt-5 overflow-hidden">
      <div className="px-5 pb-4 pt-5">
        <h2 className="m-0 text-[15px] font-semibold" id="customize-heading">Customize</h2>
        <p className="m-0 mt-1 text-[13.5px] leading-relaxed text-mc-muted">Shape the benchmark around your question. Discuss these choices with your coding agent, then agree on the setup before running it.</p>
      </div>
      <div aria-labelledby="customize-heading" className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-mc-accent" role="region" tabIndex={0}>
        <table className="w-full min-w-[760px] border-collapse text-[13px]">
          <caption className="sr-only">Benchmark design choices and alternatives</caption>
          <thead className="bg-mc-surface-2 text-left text-xs text-mc-muted">
            <tr>
              <th className="w-[22%] px-5 py-3 font-semibold" scope="col">Decision</th>
              <th className="w-[39%] px-5 py-3 font-semibold" scope="col">Option</th>
              <th className="w-[39%] px-5 py-3 font-semibold" scope="col">Alternative</th>
            </tr>
          </thead>
          <tbody>
            {DECISIONS.filter(decision => !textV2 || decision.name !== "Severity weights").map((decision) => (
              <tr className="border-t border-mc-line align-top" key={decision.name}>
                <th className="px-5 py-4 text-left font-semibold" scope="row">{decision.name}</th>
                {decision.options.map(([label, description]) => (
                  <td className="px-5 py-4" key={label}>
                    <p className="m-0 font-medium">{label}</p>
                    <p className="m-0 mt-1 leading-relaxed text-mc-muted">{description}</p>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="space-y-3 border-t border-mc-line p-5">
        <p className="m-0 text-xs leading-relaxed text-mc-muted">Ask your agent to inspect your current setup before making changes. RAND model panels provide advisory ratings; model agreement does not establish clinical validation. Preserve completed results when planning a new run.</p>
        <PromptBox displayPrompt={`Help me customize ${benchmark || "a new benchmark"}.`} lead="Discuss the setup with your coding agent:" prompt={prompt} />
      </div>
    </Card>
  );
}
