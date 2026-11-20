import type { ReactNode } from "react";
import { isOmissionItem } from "@/lib/rubric-text-v2";
import { validateTextV2ForDisplay } from "@/lib/text-v2-eligibility";
import type { TextV2Case, TextV2Criterion, TextV2Item } from "@/lib/rubric-text-v2";

const severity = (value: string | null | undefined): string => value == null ? "Not rated" : `${value[0].toUpperCase()}${value.slice(1)}`;

export function textV2RoleItems(criterion: TextV2Criterion, addOn: boolean): TextV2Item[] {
  return criterion.recommendations.filter((item) => !isOmissionItem(criterion, item) && (item.addOn === true || item.optional === true) === addOn)
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
}

function ItemRows({ criterion, addOn }: { criterion: TextV2Criterion; addOn: boolean }): ReactNode {
  const items = textV2RoleItems(criterion, addOn);
  const omission = !addOn ? criterion.recommendations.find((item) => isOmissionItem(criterion, item)) : undefined;
  return <section aria-label={addOn ? "Add-ons" : criterion.kind === "counseling" ? "Main actions" : "Main approach"} data-role-zone={addOn ? "side" : "main"}>
    <h3 className="mb-2 text-sm font-semibold">{addOn ? "Add-ons" : criterion.kind === "counseling" ? "Main actions" : "Main approach"}</h3>
    {addOn && <p className="mb-2 text-xs text-[hsl(var(--muted-foreground))]">Good or bad extras alongside the main approach. They do not fulfill the criterion on their own.</p>}
    <div className="overflow-x-auto"><table className="w-full border-collapse text-left text-sm">
      <thead><tr className="border-b border-[hsl(var(--border))] text-xs text-[hsl(var(--muted-foreground))]">
        <th className="py-2 pr-3" scope="col">Item</th><th className="py-2 pr-3" scope="col">Approach</th><th className="py-2 pr-3" scope="col">Clinical Appropriateness</th><th className="py-2 pr-3" scope="col">Error Severity</th>
        {criterion.kind === "counseling" && <th className="py-2" scope="col">Harm if missed</th>}
      </tr></thead>
      <tbody>{[...items, ...(omission ? [omission] : [])].map((item) => <tr className="border-b border-[hsl(var(--border))] align-top" data-v2-item={item.id} key={item.id}>
        <th className="py-2 pr-3 font-medium" scope="row">{item.id}</th>
        <td className="py-2 pr-3">{item.text}{item.unresolved && <p className="mt-1 text-xs text-amber-900">Unresolved: {item.unresolved}</p>}</td>
        <td className="py-2 pr-3 tabular-nums">{item.score ?? "Not rated"}</td><td className="py-2 pr-3">{severity(item.harm)}</td>
        {criterion.kind === "counseling" && <td className="py-2">{"omissionHarm" in item ? severity(item.omissionHarm) : "Not required"}</td>}
      </tr>)}</tbody>
    </table></div>
    {!items.length && !omission && <p className="py-2 text-sm text-[hsl(var(--muted-foreground))]">None</p>}
  </section>;
}

export default function TextV2RubricPanel({ record, validationProvenance = {} }: { record: TextV2Case; validationProvenance?: Record<string, unknown> }): ReactNode {
  const check = validateTextV2ForDisplay(record, "draft", validationProvenance);
  return <div className="space-y-5" data-rubric-text-v2>
    <p className="text-xs text-[hsl(var(--muted-foreground))]">Clinical Appropriateness uses the 1-9 RAND/UCLA scale. Error Severity is measured against the best option.</p>
    {record.unresolved && <p className="text-sm text-amber-900">Unresolved: {record.unresolved}</p>}
    {check.errors.length > 0 && <div className="rounded-md border border-orange-200 bg-orange-50 p-3 text-sm text-orange-900" role="alert"><strong>Rubric needs attention</strong><ul className="mt-1 list-disc pl-5">{check.errors.map((error) => <li key={error}>{error}</li>)}</ul></div>}
    {check.warnings.length > 0 && <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><strong>Rubric warnings</strong><ul className="mt-1 list-disc pl-5">{check.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
    <section aria-label="C1" className="space-y-2">
      <h2 className="text-sm font-semibold">C1: Usual care</h2>
      <p className="text-sm">Continue current management or usual care, without additional input</p>
      <dl className="flex flex-wrap gap-6 text-sm"><div><dt className="text-xs text-[hsl(var(--muted-foreground))]">Clinical Appropriateness</dt><dd>{record.usualCare?.score ?? "Not rated"}</dd></div><div><dt className="text-xs text-[hsl(var(--muted-foreground))]">Error Severity</dt><dd>{severity(record.usualCare?.harm)}</dd></div></dl>
    </section>
    {record.decisions.map((criterion) => <section aria-label={criterion.id} className="space-y-4 border-t border-[hsl(var(--border))] pt-4" data-v2-criterion={criterion.id} key={criterion.id}>
      <h2 className="text-sm font-semibold">{criterion.id}: {criterion.question}</h2>
      {criterion.unresolved && <p className="text-sm text-amber-900">Unresolved: {criterion.unresolved}</p>}
      <ItemRows criterion={criterion} addOn={false} /><ItemRows criterion={criterion} addOn />
    </section>)}
  </div>;
}
