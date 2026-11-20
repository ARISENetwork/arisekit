import { notFound, redirect } from "next/navigation";

import { getCurrent } from "@/lib/caseset/current";
import { runsRedirect } from "@/lib/caseset/routes";

interface Props { params: Promise<{ caseset: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }

export default async function CasesetPage({ params, searchParams }: Props): Promise<never> {
  const { caseset } = await params;
  if ((await getCurrent())?.bench.name !== caseset) notFound();
  redirect(runsRedirect([caseset], await searchParams));
}
