import { notFound, redirect } from "next/navigation";

import { getCurrent } from "@/lib/caseset/current";
import { runsRedirect } from "@/lib/caseset/routes";

interface Props { params: Promise<{ caseset: string; caseId: string; version: string }> }

export default async function TablePage({ params }: Props): Promise<never> {
  const { caseset, caseId, version } = await params;
  if ((await getCurrent())?.bench.name !== caseset) notFound();
  redirect(runsRedirect([caseset, caseId, "table", version], {}));
}
