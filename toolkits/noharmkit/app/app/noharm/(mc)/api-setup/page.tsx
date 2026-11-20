import type { ReactElement } from "react";
import ApiModelSetup from "@/components/mc/ApiModelSetup";
import { getCurrent } from "@/lib/caseset/current";
import { loadModelSetup } from "@/lib/api-model-setup";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function ApiSetupPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }): Promise<ReactElement | null> {
  const query = await searchParams;
  if (query.review === "api-models") redirect("/noharm/api-setup");
  const current = await getCurrent();
  if (!current) return null;
  const setup = await loadModelSetup(current);
  return <ApiModelSetup project={setup.project} initialConfig={setup.config} models={setup.models} catalogError={setup.catalogError} editable={setup.editable} />;
}
