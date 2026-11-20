import { notFound, redirect } from "next/navigation";

import { getCurrent } from "@/lib/caseset/current";
import { runsRedirect } from "@/lib/caseset/routes";

interface Props { params: Promise<{ caseset: string; caseId: string; model: string; trial: string }> }

export default async function ResponsePage({ params }: Props): Promise<never> {
  const { caseset, caseId, model, trial } = await params;
  if ((await getCurrent())?.bench.name !== caseset) notFound();
  redirect(runsRedirect([caseset, caseId, "response", model, trial], {}));
}
