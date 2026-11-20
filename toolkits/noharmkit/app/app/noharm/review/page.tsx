import { notFound } from "next/navigation";

import TextV2RubricEditor from "@/components/TextV2RubricEditor";
import AnswerTableEditor from "@/components/AnswerTableEditor";
import ReviewArrival from "@/components/ReviewArrival";
import { getCurrent } from "@/lib/caseset/current";

export const dynamic = "force-dynamic";

interface ReviewPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

// The rubric editor is the full review workspace; the toolkit shell stays on the pipeline pages.
export default async function ReviewPage({ searchParams }: ReviewPageProps): Promise<React.ReactNode> {
  const q = await searchParams;
  const caseId = typeof q.case === "string" ? q.case : "";
  const version = typeof q.version === "string" ? q.version : "";
  const current = await getCurrent();
  if (!current) notFound();
  const { bench } = current;
  const c = bench.cases.find((x) => x.caseId === caseId);
  const table = c?.page.tables.find(t => t.version === version && (t.record || t.textV2));
  if (!c || !table) notFound();
  const Editor = table.textV2 ? TextV2RubricEditor : AnswerTableEditor;
  return (
    <main className="bg-[hsl(var(--background))] text-[hsl(var(--foreground))] [color-scheme:light]">
      <ReviewArrival>
        <Editor caseId={caseId} reviewState={c.versionStates[version] ?? "draft"} source={{ caseset: bench.name, version }} synthetic={c.page.provenance.synthetic === true} {...(table.textV2 ? { validationProvenance: { judge_scoring_source_commit: c.page.provenance.judge_scoring_source_commit } } : {})} />
      </ReviewArrival>
    </main>
  );
}
