import { isOmissionItem, type TextV2Case } from "@/lib/rubric-text-v2";
import { Prose } from "@/components/mc/ui";

const count = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

// What a rubric covers, without its ratings: the editor holds every detail.
export default function RubricSummary({ record }: { record: TextV2Case }) {
  const items = record.decisions.reduce((total, criterion) => total + criterion.recommendations.length, 0);
  return <section aria-label="Rubric summary">
    <p className="m-0 text-xs text-mc-muted">{count(record.decisions.length, "criterion", "criteria")}, {count(items, "item", "items")}, plus usual care</p>
    <ol className="m-0 mt-2 list-none p-0">
      {record.decisions.map((criterion) => {
        const listed = criterion.recommendations.filter((item) => !isOmissionItem(criterion, item));
        const addOns = listed.filter((item) => item.addOn).length;
        return <li className="flex items-start gap-3 border-t border-mc-line py-2.5 first:border-t-0" key={criterion.id}>
          <span className="w-7 shrink-0 pt-px text-xs font-semibold text-mc-muted">{criterion.id}</span>
          <span className="min-w-0 flex-1 text-[13.5px] font-medium"><Prose inline>{criterion.question}</Prose></span>
          <span className="shrink-0 pt-0.5 text-xs text-mc-muted">{count(listed.length - addOns, "approach", "approaches")}, {count(addOns, "add-on", "add-ons")}</span>
        </li>;
      })}
    </ol>
  </section>;
}
