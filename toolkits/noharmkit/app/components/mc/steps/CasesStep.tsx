import { datasetFields } from "@/lib/dataset-fields";
import StepFrame, { caseOf, StepPanel } from "@/components/mc/StepFrame";
import type { StepProps } from "@/components/mc/StepFrame";
import { Prose } from "@/components/mc/ui";

export default function CasesStep({ bench, params }: StepProps) {
  const c = caseOf(bench, params);
  const fields = datasetFields(c.page.source);
  return (
    <StepFrame
      bench={bench}
      equalColumns
      inputs={<Prose>{c.page.source.presentation}</Prose>}
      inputsTitle="Task"
      outputs={<Prose>{fields.solutions.join("\n\n")}</Prose>}
      outputsTitle="Solution"
      outputsBelow={<StepPanel title="Errors">{fields.errors ? <Prose>{fields.errors}</Prose> : <p className="m-0 text-mc-muted"><em className="italic">None provided</em></p>}</StepPanel>}
      params={params}
      step="cases"
    />
  );
}
